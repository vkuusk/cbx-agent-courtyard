# Spike 6a — delivery into a live Claude Code session

> Lab notebook: the recorded observations are as run, but the wording follows the
> vocabulary decision in design §3 — hub → agent is **delivery**, and "injection" names
> only the *attack* (prompt injection). Directory and script names were renamed to match
> (`resume-inject/inject.sh` → `resume-deliver/deliver.sh`), so commands recorded here are
> the current ones. The one "inject" left on this page is Claude Code's own startup
> string, quoted verbatim in Experiment A.

- **Question:** which mechanism(s) deliver a courtyard message into a Claude Code agent?
- **Outcome goes to:** design doc §13 as **D-spike** (delivery stack for step 6).
- **Everything in `spikes/` is throwaway** — the real adapter (6b/6c) reuses the
  *mechanisms*, never this code.
- Docs research (2026-08-20, Claude Code 2.1.237): channels are a research-preview
  feature — an MCP stdio server declaring the `claude/channel` capability can push
  events that become live turns ([channels](https://code.claude.com/docs/en/channels),
  [reference](https://code.claude.com/docs/en/channels-reference)). Events queue while
  Claude is busy and deliver on the next turn. Custom channels need
  `--dangerously-load-development-channels`. The spike verifies this empirically on
  this machine, plus the two alternatives.

Prerequisites (verified present): bun 1.3.4, Claude Code ≥ 2.1.237, claude.ai login.
Each experiment burns a few real turns — keep the asks trivial.

---

## Experiment A — channel push (the design's primary mechanism)

```sh
cd spikes/6a-delivery/channel
bun install                     # once; pulls @modelcontextprotocol/sdk
claude --dangerously-load-development-channels server:courtyard
```

Accept the full-screen development-channels warning ("I am using this for local
development") and the "New MCP server found in this project: courtyard" consent.
Look for the dim startup notice: `Channels (experimental) messages from
server:courtyard inject directly in this session`.

**Terminal 2** — watch Claude's replies:

```sh
curl -N localhost:8790/events
```

**Terminal 3** — push messages in:

```sh
# A1: idle session — does the message arrive as a live turn, unprompted?
curl -d "This is fake-infra. What directory are you working in? Reply via courtyard_reply." \
     -H "X-From: fake-infra" localhost:8790

# A2: while A1's reply prompt is pending/running, or ask Claude (terminal 1) to
#     "count to 30 slowly, one number per second, using sleep" first — then:
curl -d "URGENT from fake-infra: stop counting and tell me a joke instead." \
     -H "X-From: fake-infra" localhost:8790
```

**Record (run 2026-08-20, Claude Code 2.1.237, claude.ai login):**
- [x] A1: message appeared as a turn in the idle session without touching terminal 1
      (terminal showed `← courtyard: This is fake-infra…`)
- [x] A1: Claude called `courtyard_reply`; reply arrived on `/events` (auto mode
      approved the tool call without a prompt)
- [ ] A2: queue-while-busy NOT exercised (both deliveries hit an idle session;
      docs say events queue and deliver on the next turn) — optional re-test
- [x] latency idle → turn started: effectively immediate
- [x] surprising (good): with only the server `instructions` string, Claude treated
      the URGENT delivered text as peer-agent DATA, declined its false premise, and
      flagged it as a possible redirect probe — the peer-content-is-data posture
      (since formalized as authority grading, §7.5) holds even before the full
      wrapper exists

## Experiment B — Stop-hook backstop (verified; not adopted in v1 — design D14)

```sh
cd spikes/6a-delivery/stop-hook
echo "fake-infra says: after you finish, reply (in the terminal) with the word PONG" > messages.txt
claude
```

In the session ask something trivial ("what files are in this directory?"). When it
finishes answering, the Stop hook should fire, find messages.txt, and block the stop.

**Record (run 2026-08-20, Claude Code 2.1.237):**
- [x] the stop was blocked (UI: `Ran 1 stop hook → Stop hook error: …`) and Claude
      processed the delivered text: replied PONG
- [x] text surfaced; hook emitted both `systemMessage` and `reason` so the run doesn't
      isolate which — if ever adopted, emit both (docs say `systemMessage` is current)
- [x] second stop passed cleanly (no loop)
- [x] bonus finding: Claude read messages.txt during its normal work (listed the
      directory and quoted the pending message BEFORE the hook fired). Decision
      (architect, 2026-08-20): unread/seen state lives in the HUB API — no local
      mailbox/state files at all. Later the same day the hook itself was dropped from
      v1 (D14): its coverage is hub-detectable and operator-fixable, and a second
      agent-side mechanism is a second thing to port per agent type.
- [ ] idle no-wake: definitionally true (hooks only run at lifecycle points); not
      separately exercised

## Experiment C — `-p --resume` subprocess delivery (vkuusk's scheme)

**Terminal 1:**

```sh
cd spikes/6a-delivery/resume-deliver
claude --name courtyard-spike-c
# REQUIRED FIRST: say "remember the codeword BLUEBIRD, reply OK" and wait for the OK.
# A session with zero turns persists nothing — --resume finds no such title
# (learned the hard way on the first attempt).
```

**Terminal 2, while terminal 1's session stays open:**

```sh
cd spikes/6a-delivery/resume-deliver
./deliver.sh courtyard-spike-c "what is the codeword? answer with just the word"
```

**Record (run 2026-08-20, Claude Code 2.1.237):**
- [x] the headless turn saw the transcript: answered BLUEBIRD. On-disk check: ONE
      transcript file, same session id as the interactive session, all four turns in
      order — the delivered turn appended to the live session, no fork
- [x] title (`--name`) lookup works while the session is open — but only once the
      session has at least one persisted turn (zero-turn sessions are unresumable)
- [x] terminal 1 did NOT show the delivered exchange live
- [x] divergence probe: terminal 1's in-memory context did NOT include the delivered
      turns ("you asked me to remember the codeword")
- [x] wall-clock cost of one delivery: ~3.6s on a 2-turn transcript (grows with
      transcript length — full context reload per delivery)
- [x] after closing both, `--resume` showed ONLY terminal 1's turns. On-disk parent
      chains confirm why: the delivered question and terminal 1's next question share
      the same parent node — the transcript became a TREE, resume follows the newest
      branch, and the delivered branch is orphaned. **Verdict: safe and lossless
      against a CLOSED session; racing an OPEN session silently loses the delivery.**

## Verdict (all three run 2026-08-20 on Claude Code 2.1.237 → design §13 D-spike)

| Mechanism | Works? | Idle agent | Busy agent | Closed session | Risks |
|---|---|---|---|---|---|
| A channel push | **yes** | immediate turn | queues, next turn (per docs; not exercised) | n/a (session must be open) | research preview: dev flag + startup warning; contract may change |
| B stop hook | **yes** | no wake | delivered at next stop | n/a | 8-block override; emit both `systemMessage`+`reason` |
| C `-p --resume` | **yes, closed only** | — | **forks the transcript tree; delivered branch orphaned** | **yes — context-preserving wake** | ~full-context cost per turn; concurrency undocumented and empirically lossy |

**Delivery stack for step 6:** A primary (live sessions), B backstop (unread queried
from the hub API — no local state files, architect decision), C reserved for
launching/waking a *closed* agent with context intact (`--resume` keeps the session
id) — never for concurrent delivery. Adapter = one stdio MCP server per agent
(channels are stdio-only) exposing the courtyard tools on the same server. Launch
commands must include `--dangerously-load-development-channels server:courtyard`
while channels are in research preview (full-screen consent at each start).
