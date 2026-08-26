# Feedback items from the architect's test cycles

The architect tests the courtyard with real Claude Code agents and records what he
observes here, one item per observation or question, **stated but not answered**. Action
items are discussed and decided only after a review cycle is complete; until then every
item is *open*. Decisions taken from an item are recorded in the design doc's decision log
(`docs/design/architecture-v1-2026-08-18.md` §13) and the step plan
(`v1-implementation-steps.md`), and the item is marked with a pointer to them.

Conventions: items keep the architect's numbering; the *Touches* line lists where the
subject lives today (facts, not proposals); `Status` is `open` → `discussed` → `decided
(Dnn / step n)` or `dropped`.

---

## Review cycle 1 — started 2026-08-23

Setting: two Claude Code agents registered by the architect (`cbxorg-infra`, owner of
deploying AWS resources; `terraform-developer`, owner of terraform modules for AWS) on one
supervised line, exchanged messages about an RDS module, operator notes sent to both.

### 1. Model choice for a Claude Code agent

**Asked.** Can a Claude Code agent be started with a particular *model*? Can the model be
set from the hub?

**Why.** The default model may not suit a given agent, and people forget to set it when
launching.

**Touches.** Launch is manual in v1 (design §7.2, §8): the operator starts
`claude --dangerously-load-development-channels server:courtyard` in the agent's workdir;
the hub's footprint in that directory is the project `.mcp.json` written by install
(`hub/core/install.py`, `courtyard-invite`). The agent record (§5.1) has no model field.

**Status.** decided 2026-08-24 → **WP‑A** (done): `agents.model` + install writes it
into `.claude/settings.local.json` and the launch command.

### 2. Claude Code status line showing the registered agent's name

**Asked.** Can the Claude Code status bar be customised to show the agent's registered
courtyard name? The install step that writes `.mcp.json` could also update the file that
customises the status line.

**Why.** With several terminals open, the operator needs to see at a glance which agent a
terminal belongs to.

**Touches.** Install writes only the project `.mcp.json` (design §7.2, D14: no
`.claude/settings.json` written today; D15 token placement). Claude Code's status line is
configured outside `.mcp.json`.

**Status.** decided 2026-08-24 → **WP‑A** (done): install sets a status line showing
the courtyard name, only when the agent has none.

### 3. The note on a held message travels with the verdict

**3.1 Asked.** In the queue (a message held at the gate on a supervised line), the *note
to the agent* should be sent together with the decision — approve / return-to-sender /
reject. The note goes out when what to do with the message is already decided:
**approve-with-comment**, **return-with-comment**.

**Observed.** In the screenshot the notes typed into the bottom box went out as stand-alone
operator notes to both agents (`you → cbxorg-infra`, `you → terraform-developer`, 21:03),
separate from any verdict on the held message.

**Touches.** Design §5.5 (an approval may carry a note delivered as an `operator_note`; a
return always carries the comment as the payload of the return notice); WebUI: the
verdict buttons on a held message read their note from the bottom box; Enter in the box
sends a plain note (`webui/js/composer.js`, `conversation.js`).

**3.2 Asked (maybe).** Rename the verdict `reject` to **`drop`**.

**Touches.** Design §5.4 rule 4 (`reject` — dropped, kept in history with
`status: rejected`), §5.5, the envelope's hub notices (`hub/core/envelope.py`), API and
WebUI labels.

**3.3 Observed.** When answering another agent's question, agents append a question of
their own at the end — "Do you want me to do something else?", "Want me to go ahead and
scope/build it, or hold…?", "do you actually want an RDS wrapper module scoped at some
point?". Such trailing questions can start a long exchange about something unrelated to the
task at hand.

**Touches.** What the model sees is rendered by the hub — the envelope and preamble
(design §7.5, `hub/core/envelope.py`) and the tool descriptions in
`adapters/claude_code/mcp_server.py`; the gate is the operator's only intervention point
on a supervised line.

**Status.** 3.1 decided 2026-08-24 → **WP‑B** (done, confirmed 2026-08-24; the hub already delivered the
verdict note this way — `board.py`; the WebUI is what changes). 3.2 **decided: keep
`reject`** (architect, 2026-08-24). 3.3 discussed → **WP‑C**, awaiting the architect's go.

### 4. "Add an agent" form — field order and multiline descriptions

**Asked.** The form should show **name, type, directory, colour** first; **under** them,
two **multiline** entries: *What is this agent for?* and *What does it own?*.

**Observed.** Today (Agents page) row 1 = name · type · "what is this agent for?" · "what
does it own?" as single-line inputs; row 2 = project dir · colour swatches · *add agent*.

**Touches.** `webui/js/views/agents.js`; the two texts are `Agent.description` and
`Agent.sme_domain` (design §5.1, §7.5).

**Status.** discussed → **WP‑D**, awaiting the architect's go

### 5. Two modes of agent discovery: auto-discovery and manual links

**Asked.** Auto-discovery through MCP (`courtyard_peers` returns every registered agent)
is good, but it relies on the agents themselves knowing the rules of courtyard interaction
and safety. Proposal for two discovery modes:

- **(a) auto-discovery** — as today: an agent sees all other agents registered in the hub;
- **(b) manual links** — the operator adds a line explicitly in the hub ("link agents"),
  and the discovery call returns only the agents linked to the caller. The MCP mechanism
  stays; the list is "all linked" instead of "all registered".

**The architect asks** whether I see value in (b) and what opportunities it creates —
e.g. groups of agents working in separate sub-teams.

**Touches.** `GET /api/agents/{id}/peers` and `hub/core/peers.py` (ranked, trimmed and
worded by the hub, D14); lines are created automatically on first send (design §5.2 — no
"create line" ceremony today); board and wires in the WebUI.

**Status.** discussed 2026-08-24 — value confirmed (the boundary moves into the hub;
sub-teams; a link can be a pre-created idle line) → **WP‑E**, design proposal first (D22
candidate), awaiting the architect's go

### 6. Operator note direction on a line — the "note → both" chip

When reviewing a line, the operator's note can be directed to the agent on either end of
the line or to both agents; the composer chip currently reads `note → both`.

**6a Asked.** What would be a use case for a note to *both* agents connected by the line?

**6b Observed.** The `note → both` label in the input box for a line's conversation looks
the same as the label in the input box for a direct message to an agent — but one is
changeable (click to cycle the destination) and one is static. Confusing: you have to
*know* whether a click is needed to change the destination.

**6c Asked.** If this input is considered the note/comment for the accept or return
action, the destination switch is not needed at all: comment on **accept** → sent to the
recipient, appended to the original message; comment on **return** → sent to the sender,
appended to the original message. (Extends item 3.1 — the note travels with the verdict.)

**Touches.** `webui/js/composer.js` (`plan()`: the agent chip is a static span with name +
status dot; the line chip is a button cycling both → a → b); design §5.6 (an
`operator_note` is targeted to a, b, or both — operator's choice, default both); §5.5
(approve note delivered as an `operator_note`; the return comment *is* the payload of the
return notice).

**Status.** 6a **closed 2026-08-24** — a use case exists and cycle 1 produced it: the
21:03 standing instruction sent to both participants (policy/context corrections both
sides must hear); notes to a line stay. 6b + 6c decided → **WP‑B** (done, confirmed).

### 7. The token-spending cycle; Claude Code asks permission for `courtyard_send`

Two observations from one exchange.

**7.1 Observed.** The token-spending cycle: "do we have an RDS module" → "no — do you
need me to create one?" → "thanks for the offer, but it's not up to me to decide." A full
delivery-and-reply cycle (tokens, gate decisions, operator attention) spent on walking
back an offer nobody asked for. (Same root as 3.3 — trailing questions.)

**7.2 Observed.** That last reply triggered Claude Code's tool-permission prompt in the
agent's terminal:

```
Tool use:  courtyard — Courtyard Send Tool: (MCP)
Do you want to proceed?
  1. Yes
  2. Yes, and don't ask again for courtyard — Courtyard Send commands in /Volumes/…
  3. No
```

The agent sits blocked until the human answers in that terminal.

**Asked.** We need to pre-approve this tool use — talking to the courtyard over MCP.

**Touches.** Install writes only the project `.mcp.json` (design §7.2; D14 — no
`.claude/settings.json` written today; the same boundary as item 2); Claude Code tool
permissions (allow rules such as `mcp__courtyard__…`) live in the project's
`.claude/settings.json` / `settings.local.json`, outside `.mcp.json`.

**Status.** 7.1 discussed (same root as 3.3) → **WP‑C**, awaiting the architect's go.
7.2 decided 2026-08-24 → **WP‑A** (done).

### 8. Agents page: two buttons per row — Edit and Remove

**Asked (2026-08-24, after trying WP‑A).** Keep only **Edit** and **Remove** on the agents
list; **launch config** and **rotate token** belong inside an **Edit Agent** view.

**Touches.** `webui/js/views/agents.js` (the three per-row action buttons, `LaunchPanel`,
`NoTokenPanel`). No Edit Agent view exists yet; the known gaps that would live there too:
colour and model cannot be changed after creation (no hub endpoint for editing an agent's
fields yet — create, token and remove only).

**Status.** discussed → folded into **WP‑D** (widened from the add-form layout to the
Agents-page rework), awaiting the architect's go

### 9. Two bugs from the WP‑A check: no release on your own line; the draft follows you

**Observed (2026-08-24).** a) After a hub restart the operator's line with `cbxorg-infra`
was still `awaiting_reply` on yesterday's unanswered message — the box said "waiting for
cbxorg-infra to reply" with no way out, because the **release** button existed only on
agent↔agent lines. (The disabled box itself is the turn rule §5.4 working; the missing
valve was the bug.) b) Text typed into a line's note box reappeared, greyed out, in the
agent's disabled box — the draft was one global string, not tied to what it was typed
for.

**Fixed the same day.** Release shows on **any** line in `awaiting_reply`, the operator's
own included (§5.4 rule 6 always allowed it hub-side — `POST /api/lines/{id}/release`
never cared whose line it was); drafts are stored per selection, so text stays with the
agent or line it was typed for (`webui/js/store.js` `select`/`setDraft`,
`conversation.js` `Header`).

**Status.** fixed 2026-08-24, confirmed with the WP‑B check

### 10. Turn obligations outlive the agent sessions that could discharge them

**Observed (2026-08-24).** Sequence: a message to `cbxorg-infra` yesterday (never
answered) → all agents and the hub shut down → configs updated, agents started, hub
started → **the first message of the new day is blocked**. The line was still
`awaiting_reply` from yesterday.

**Review (senior engineer, same day).** A line unblocks only by the addressee's reply,
release, or archive. Nothing else touches turn state: not stale/gone (liveness is
deliberately decoupled, §5.1), not detach, not re-attach (backlog re-push covers
`queued` messages only — `channels.attach`/`deliver_backlog`), not a hub restart. The
flaw: the obligation is durable but the session that could discharge it is ephemeral —
the message was `delivered` to *yesterday's* session, today's session never saw it, so
the hub holds an obligation nobody alive can fulfil.

**Proposed remedies (layered, awaiting the architect's decision):**
- **R1** re-arm on attach: a line awaiting X whose in-flight message was delivered before
  X's current attachment flips that message back to `queued` → normal backlog push into
  the new session (+ a "redelivered" system note). Hub-only; the obligation itself is
  unchanged and finally dischargeable.
- **R2** operator supersede: on the operator's own line, a new operator message while the
  agent owes a reply to the operator = implicit release + send (system entry). Relaxes
  §5.4 for operator lines only — the turn rule stays as backpressure for agents.
- **R3** visibility: "owes you a reply" badge on the agent card + real state in the pane
  header (extends item 9's ergonomics).

**Status.** discussed — remedies proposed, awaiting the architect's decision

**Parked (architect: "we'll return to this later").** Unblocking by having the agent send
anything ("How are you doing?") makes that message *the formal reply* to the stale
question — the turn machine pairs any send by the owing side with the in-flight message.
Semantic reply-pairing is a casualty of the same root cause.

### 11. Delivered-but-lost: channel events vanish inside a stale Claude Code session

**Observed (2026-08-24 evening).** Two operator messages to `cbxorg-infra` (21:52,
21:57) were pushed and ACKed in ~20 ms to the current, freshly-attached, heartbeating
channel — yet never surfaced in the session: no turn started while idle, nothing arrived
on later turns, and `courtyard_inbox` was rightly empty (the hub correctly holds them
`delivered`). The adapter's whole post-ACK job is one stdout line
(`notifications/claude/channel`), so the loss is inside Claude Code. Both terminals
showed **"✔ Update installed · Restart to update"** — Claude Code had auto-updated under
the running sessions; yesterday's pre-update session delivered fine. Channels are a
research preview; the D-spike note predicted contract drift.

**Remedy in practice.** Restart agent sessions after the update banner appears (and after
any Claude Code auto-update); if a drop recurs on a fresh session, read the courtyard MCP
server's stderr log (`/mcp` → courtyard) — every delivery is logged there. Hub-side there
is no cheap detector: the adapter cannot confirm model-read (accepted in D14), so
"delivered" is as far as the hub can honestly see.

**Root cause (found in the 2.1.241 bundle after a restart did NOT cure it).** The
channels preview contract drifted between 2.1.237 and 2.1.241: the session's
allowed-channels list — the one the "not in --channels list" check reads — is now
populated **only by the new `--channels` flag**; `--dangerously-load-development-channels`
alone just authorizes a dev server and no longer enrolls it. Every session launched the
old way connects, serves tools, ACKs pushes — and Claude Code skips the channel events
("Channel notifications skipped" in the courtyard MCP log; yesterday's pre-update session
logged "Channel notifications registered"). The D-spike note predicted exactly this
class of drift.

**Resolution (same night, empirically — the preview drifted TWICE).** A pty-driven probe
of all flag forms on the then-current Claude Code (auto-updated again mid-evening, to
2.1.245) settled it: the **original single flag registers the channel again**
(`--dangerously-load-development-channels server:courtyard`), while the 2.1.241-era
two-flag workaround now *fails* the allowlist check, and `--channels` alone never shows
the consent. Timeline: ≤2.1.237 original flag OK → 2.1.241 broke it ("not in --channels
list") → 2.1.245 restored it and broke the workaround. The launch command is reverted
everywhere; `tests/communications/oper-agent1-oper.py` (written for this) proves the full
operator → agent1 (live Claude Code, haiku) → operator round trip and prints the
channel's registered/skipped verdict on failure — **PASS on 2.1.245**.

**Status.** resolved 2026-08-24 — original flag restored, round-trip test green; ops
rule: after a Claude Code auto-update, restart agents and run the communications test if
messages stop arriving

### 12. Agents launched before the hub stay offline forever

**Observed (2026-08-24, late evening).** After relaunching both agents (hub still down at
that moment), the cards sat **offline** indefinitely even once the hub was up.

**Root cause.** The adapter tried to attach **5 times over ~10 seconds and then gave up
for the life of the session** (`mcp_server._start_channel`); the heartbeat loop — whose
`not_attached` handling would have recovered everything — only starts *after* a
successful attach. Agents-first-hub-second is the operator's normal habit, so losing that
race permanently was a real resilience bug, not user error.

**Fixed the same day.** Attach retries forever, every 2 s (one log line on the first
miss, then about once a minute). New e2e test
`test_adapter_attaches_when_the_hub_arrives_late`: adapter launched against a silent
port, the hub appears 11 s later, the agent must reach `connected`. 142 tests.

**Status.** fixed and confirmed 2026-08-24 — launch order no longer matters

### 13. Shift — one button starts (and stops) the whole team

**Asked (2026-08-25).** Starting the courtyard today means: open a terminal per agent,
`cd` to each workdir, paste each launch command, start the hub. It should be: **start the
hub, press "Start shift"** — and every registered agent that is not already up gets
started (new terminal window → `cd <workdir>` → launch command). The terminal application
is a setting on the Admin page.

**The term (renamed from "Session" the same day).** A **Shift** = the operator's working
period: all registered agents are started when it begins and stopped when it ends. Chosen
over "Session" because that word is already taken three times over (Claude Code's
resumable sessions — item 10 turns on them — plus browser and DB sessions), and because
the metaphor is exact: the team clocks in, works under the operator's watch, clocks out.
Named in contrast to a possible future *autonomous team* mode (agents running between
shifts, without an operator, or with several operators) — that mode is explicitly **not**
being designed now.

**Team mode (added same day).** The shift behaviour is one value of a new setting, **Team
mode**: **`On shift`** (agents' lifetimes are tied to the operator's working period — v1,
the only implemented value) | **`Always on`** (agents run independently of anyone's
presence — future, shown disabled). Named around the lifecycle axis deliberately: the
architect also floated "Single User vs Service", but that names the *audience* axis
(multi-operator, auth, tenancy) which sits behind the §2 non-goals fence and isn't what
this setting controls — a single operator can legitimately run always-on. "Crew" was
dropped as a synonym for the existing term **Team** (one name per concept).

**UI (agreed 2026-08-25).** Admin is the only place the *mode* changes: a **Team mode**
pill `On shift | Always on` (same two-state idiom as `supervised | auto-pass`; *Always
on* disabled, "not yet available"), in a Team section that also holds the terminal
application (per-agent membership toggle deferred — v1 shifts include all registered
agents). The Courtyard page informs but never changes the mode, and the information and
the daily control are **the same element**: one pill, top right of the Team panel header
— its presence says the team runs on shifts, its state says where the shift stands: idle
`▶ Start shift`; starting `Starting · 2/3` (per-agent progress lives where it already
does — the card status dots); running `● 3/3 on shift` with **End shift** revealed on
click. Under *Always on* the pill would be replaced by a small static `always on` tag —
no second "Team mode: …" label anywhere on the board.

**Decisions on the known hazards (architect, 2026-08-25):**
- **Double-launch** (after a hub restart healthy agents look down until their heartbeat
  re-attaches — spawning then would fork a live session, seen in cycle 1): shift start
  waits out one re-attach window with a visible **countdown** (30…0) before launching
  whatever is still `gone`; also consider shortening the heartbeat interval to ~15 s —
  for 3–5 agents the overhead is negligible.
- **Stop semantics**: no graceful remote shutdown for now — ending the shift closes what
  the shift started (tracked window/PID), manually started terminals are left alone.
- **First-run dialogs** (`.mcp.json` trust, channel consent — cannot be pre-approved):
  accepted — a brand-new agent's first shift start needs a keypress in its terminal;
  revisit only if it proves frustrating in practice.

**Touches.** Launch is manual today (design §7.2, §8; step 6e "L1 launch" was parked by
D16 — this is its return as an operator gesture, which keeps D14 intact: the hub spawns
only because the operator pressed the button). Pieces that exist: per-agent launch command
(launch config: workdir, channel flag, `--model`), channel liveness
(connected/stale/gone), attach-retries-forever (item 12) making launch order irrelevant.
New seams: a per-adapter-type **launch recipe** (the shift must not know how to start a
Claude Code agent specifically; a future headless/puppet agent would be a background
process with no terminal), terminal spawning on macOS (`osascript` → Terminal.app /
iTerm2), an Admin setting, shift-spawn tracking for stop.

**Status.** discussed 2026-08-25 → **WP‑F**; design §8.1 accepted the same day (**D23**);
implemented 2026-08-26 (migration 0010 settings table, `hub/core/shift.py` + `spawn.py`,
`/api/shift` + `/api/settings`, SSE `shift`, board pill, Admin → Team, heartbeat 30→15 s;
18 new tests, runbook script + manual spawn procedure, quickstart step 4 rewritten).

**Live check (architect, 2026-08-26): start worked** — countdown, both terminals opened,
`● 2/2 on shift`. Two findings, fixed the same day:
- **Stopping was not discoverable** ("start was obvious"; the running pill's only hint
  was a hover tooltip). Fix: the running state is a status pill **plus an explicit
  `■ End shift` button** with a square stop icon, mirroring `▶ Start shift`.
- **Only one of two windows closed on end.** Root cause: close SIGTERMed the window's
  tty and closed immediately — the window whose `claude` was still shutting down popped
  Terminal's "process is running" modal and survived. Fix: close now **waits for the tty
  to actually clear** (TERM up to 5 s, then KILL) before closing the window; window ids
  are captured from the spawned tab (never "front window", which could race a
  back-to-back spawn); per-window close outcomes are logged and the ended shift's spawn
  record is kept in the settings document for post-mortems.

**Re-checked and confirmed (architect, 2026-08-26):** end-shift terminated an agent
mid-work and mid-conversation and **both windows closed**; the `■ End shift` button is
in. **WP‑F done.**

### 14. One-off "No such tool available: courtyard_peers" on a fresh session

**Observed (architect, 2026-08-26, Claude Code 2.1.246).** First prompt of a freshly
launched agent session: the model said "I'll check the courtyard peers", logged
`Error: No such tool available: courtyard_peers` — then immediately recovered, called
the courtyard tools twice (peers + send) and the message went out normally, held at the
gate as expected. No delivery impact.

**Analysis (senior engineer, same day).** Not a hub defect — the send path was
untouched. Two candidate mechanisms, evidence from the 2.1.246 bundle:
- The hub-rendered texts (envelope preamble, adapter instructions) name the tools bare —
  `courtyard_send`, `courtyard_peers` — while Claude Code registers MCP tools as
  `mcp__courtyard__<name>`. Models normally bridge that gap from the tool list; this
  session tried the literal bare name once first.
- 2.1.246 ships a "tool search" feature that can **defer** MCP tools out of the initial
  tool list past a size threshold (`isToolSearchEnabled`, `isDeferredTool`,
  `analyzeMcp`/`deferredToolTokens` in the bundle) — a deferred tool is not directly
  callable until discovered, which would produce exactly this error on first use.

**Remedy.** None required — self-recovering, one extra model turn at session start at
worst. Low-cost hardening available when we touch these files anyway (**WP‑C** edits the
same envelope preamble and tool descriptions): phrase tool references so they survive
prefixing/deferral, e.g. "the courtyard MCP tools (`courtyard_send`, …)". Watch for
recurrence; if deferral starts eating actual deliveries (not just discovery), that would
be a new item.

**Touches.** `hub/core/envelope.py` (preambles), `adapters/claude_code/mcp_server.py`
(INSTRUCTIONS, tool descriptions) — the WP‑C surface.

**Status.** recorded — benign, folded as a consideration into WP‑C (awaiting go)

---

## Work packages (discussion outcome, 2026-08-24)

Cycle 1 was reviewed with the senior engineer; duplicates were merged (6c = 3.1; 7.1
shares its root with 3.3) and the items grouped into five work packages. The architect's
direction: **WP‑B and WP‑A now, then pause for his review**; WP‑C, WP‑D and WP‑E wait for
that review.

| WP | Items | The one change | Where | Status |
|---|---|---|---|---|
| **WP‑B** | 3.1, 6b, 6c (3.2: keep `reject`) | While a message is held, the box *is* the verdict's comment (Enter sends nothing); otherwise the note target is a visibly clickable control | `webui/js/composer.js`, `conversation.js` — WebUI only, hub semantics already correct | done (confirmed by the architect 2026-08-24) |
| **WP‑A** | 1, 2, 7.2 | Install also writes `.claude/settings.local.json`: `model`, a status line with the courtyard name (only if absent), `permissions.allow` for the courtyard tools; `agents.model` (migration 0009) + launch config `--model` | `hub/core/install.py`, migration, Agents form | done (2026-08-24, confirmed by the architect) |
| **WP‑C** | 3.3, 7.1 | One answer-what-was-asked etiquette line in the hub-rendered envelope preambles and the `courtyard_send` tool description | `hub/core/envelope.py`, `mcp_server.py` | awaiting go |
| **WP‑D** | 4, 8 | Agents-page rework: add form (name · type · directory · colour first, then two multiline descriptions); rows keep only **Edit** and **Remove**; an **Edit Agent** view holds launch config, rotate token, and the editable fields (description, owns, workdir, model, colour — closes the no-edit-after-creation gap; needs an update endpoint) | `webui/js/views/agents.js`, hub `PATCH /api/agents/{id}` | awaiting go |
| **WP‑E** | 5 | Manual-links discovery mode — design section first (a link can be a pre-created idle line; `peers` filters; unlinked `send` refused) | design doc (D22 candidate), then `hub/core/peers.py` + board | awaiting design proposal |
| **WP‑F** | 13 | Shift + Team mode: one pill on the Courtyard page starts every registered agent not already up (terminal window + workdir + launch command, per-adapter launch recipe) and ends by closing what it started; countdown through the re-attach window before spawning; Admin gets Team mode (`On shift` v1 \| `Always on` disabled) + terminal app | design doc **§8.1** (D23), `hub/core/shift.py` + `spawn.py`, migration 0010, `/api/shift` + `/api/settings`, board pill + `■ End shift` button, Admin → Team | done (confirmed by the architect 2026-08-26: start, both-windows end, mid-conversation termination) |

## Index

| # | Item | Area | Status |
|---|---|---|---|
| 1 | Model choice for a Claude Code agent, settable from the hub | launch / install | WP‑A done |
| 2 | Claude Code status line shows the registered agent's name | install | WP‑A done |
| 3.1 | Note on a held message travels with the verdict (approve-/return-with-comment) | gate / WebUI | WP‑B done |
| 3.2 | Rename `reject` → `drop` (maybe) | gate / vocabulary | decided: keep `reject` |
| 3.3 | Agents append trailing questions that can start unrelated exchanges | envelope / model behaviour | WP‑C awaiting go |
| 4 | "Add an agent" form: name · type · directory · colour, then two multiline descriptions | WebUI Agents | WP‑D awaiting go |
| 5 | Discovery modes: auto-discovery vs manual links (sub-teams) | peers / lines | WP‑E awaiting design |
| 6a | Use case for a note to both agents on a line? | notes / WebUI | closed — use case confirmed |
| 6b | Line chip (clickable) vs agent chip (static) look the same | WebUI composer | WP‑B done |
| 6c | Note as the verdict's comment → destination switch unnecessary (extends 3.1) | gate / WebUI | WP‑B done |
| 7.1 | Token-spending cycle: unasked offer → decline → walk-back | envelope / model behaviour | WP‑C awaiting go |
| 7.2 | Pre-approve the courtyard MCP tools (Claude Code permission prompt blocks sends) | install | WP‑A done |
| 8 | Agents rows: Edit + Remove only; launch config and rotate token inside Edit Agent | WebUI Agents | WP‑D awaiting go |
| 9 | Bugs: no release on the operator's own stuck line; draft not per-selection | WebUI | fixed, confirmed |
| 10 | Turn obligations outlive agent sessions (blocked line after a full restart) | turn machine / delivery | remedies R1–R3 proposed |
| 11 | Channel contract drift (2.1.241 broke the flag, 2.1.245 restored it): sessions ACK but skip events | Claude Code preview / launch | resolved — original flag; round-trip test PASS |
| 12 | Agents launched before the hub give up attaching and sit offline forever | adapter resilience | fixed — attach retries forever |
| 13 | Shift + Team mode (`On shift` \| `Always on`): start/end the team's working period from one Courtyard-page pill; mode changed only in Admin | launch / board / Admin | WP‑F done, confirmed |
| 14 | One-off "No such tool available: courtyard_peers" on a fresh 2.1.246 session — self-recovered | envelope wording / Claude Code tool search | recorded — consideration for WP‑C |
