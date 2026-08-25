# Courtyard v1 — Implementation Plan

- **Date:** 2026-08-18
- **Status:** Draft for architect review
- **Design doc:** [`docs/design/architecture-v1-2026-08-18.md`](../design/architecture-v1-2026-08-18.md)

## Ground rules

1. **Every step ends with something running, passing tests, and demonstrable.** No step is
   "plumbing only".
2. **Every step ends with a UX checkpoint**: the architect runs the demo, tries it, and
   explicitly approves before the next step starts. Feedback at a checkpoint is folded in
   *before* moving on — course-correcting at step N is the point of stepping.
3. **Puppet agents before real agents.** The hub, gate, turn machine, and the whole WebUI are
   built and *felt* against scriptable fakes (steps 2–5). The first real Claude Code agent
   appears only in step 6, against an already-proven hub.
4. **Tests accumulate**: `make test` runs everything from all previous steps, always green.
   The turn machine and gate — the core — get the densest coverage: they are the invariant
   every other part relies on.
5. Steps are small on purpose. Rough effort marks (S/M/L) are relative, not calendar promises.
6. **Git is the architect's.** All commits, pushes, and branches are performed by vkuusk.
   Claude leaves changes in the working tree and recommends a terse one-line commit message
   (`step N: <summary> (see docs/planning/v1-implementation-steps.md)`); implementation
   detail lives in the "Implementation status" section below, not in commit bodies.
7. **The architect is the acceptance gate** (design D17). Every step-7 page is approved by
   him after trying it in the browser, and v1 as a whole is accepted by him running the
   quickstart (`docs/quickstart.md`) the way a new operator would.

---

## Implementation status

Updated after each step's implementation and architect feedback.

| Step | Status | Date | Notes |
|---|---|---|---|
| 0 — Skeleton and harness | ✅ implemented & approved | 2026-08-18 | uv-managed project, Python 3.14 pinned via `.python-version` (pip-compatible, see README); postgres 17 via compose (`make db-up`); migration `0001` = full core schema; health endpoint with DB status; localhost-bind guard; placeholder WebUI page; 10 tests green; architect ran demo + tests |
| 1 — Core domain (registry, lines, turns, gate) | ✅ implemented & approved | 2026-08-19 | Pure turn machine (`core/turns.py`) + Postgres repos (plain SQL, one tx per mutation, line-row locking) + full REST surface: registry w/ bearer tokens, send, gate (approve/return/reject), notes, release, mode dial, consuming inbox pull, history w/ `after`. Migration `0002` added explicit `recipient` + nullable `sender` (design §5.3/§9.3 updated — operator notes and system notices need explicit addressing; NULL recipient = log-only entry). Operator auto-created at startup. 45 tests green. Demo: `scripts/step1-walkthrough.sh`, verified end-to-end. Checkpoint feedback: added operator-curated agent `description` (migration `0003`) as the discovery substrate, and started `docs/design/use-cases-explained.md` (minimal-send principle; discovery layering). Deferred to step 5: operator note target "both". Migration tooling reviewed → D13: keep the custom forward-only runner. |
| 2 — Delivery push + puppet agents | ✅ implemented & approved | 2026-08-19 | `deliver()` per design §6.1 (push w/ channel token; 2xx→delivered; failure→queued + stale; human recipient→delivered, WebUI is the tunnel); channel registry (attach/heartbeat/detach, last-attach-wins + "two sessions" warning, localhost-only endpoints); liveness sweep connected→stale→gone (advisory, configurable via `COURTYARD_HEARTBEAT_SECONDS`/`GONE`/`SWEEP`); SSE `GET /api/events` (`agent`/`line`/`message`/`gate` events, full objects); `Approver` now announces via SSE. Migration `0004`: `removed_at` — removal split from liveness `status` (design §5.1/§6.3 updated; liveness-gone re-attaches, removal revokes). Client lib `courtyard.common.client` (HubClient + ChannelReceiver); `courtyard-puppet` (echo / script:yaml / manual; manual doubles as pre-UI operator console: /pending /approve /return /reject /auto /release). Attach summary: roster w/ descriptions, lines w/ whose-turn + in-flight, queued count; backlog re-pushed in order on attach. 71 tests green (25 new, incl. real-HTTP integration: two-puppet conversation, crash/re-attach backlog, wrong channel token, liveness decay/revive, SSE). Deps: httpx+pyyaml now runtime (`uv sync` needed). Demo: `make demo` / `make demo-stop`, verified end-to-end. |
| 3 — WebUI: live board + agent admin | ✅ implemented & approved | 2026-08-20 | Vanilla ES modules, no build (`webui/`: `index.html`, `style.css`, `js/` — api/store/ui + board/line/agents views, hash router). Board: line cards w/ per-participant liveness dots, mode pill, turn state ("awaiting reply from X" / "held at the gate"), pending+queued counters, recency sort. Line view: side-aligned chat bubbles, all kinds rendered (notes amber, system centered/quiet, returned/rejected greyed + struck), gate verdicts+notes shown, sticky auto-scroll. Agents: registry table w/ liveness + last-seen, add-agent form → once-only token panel w/ copy-paste `courtyard-puppet` launch command (behavior selector), remove w/ confirm. All live via SSE; snapshot refetch on every (re)connect so missed events can't matter; message bodies rendered as text nodes only (never markup). Backend: `/api/lines` enriched (participant names, pending/queued counts, last_activity_at) and `line` SSE events now accompany every counter change (deliverer + pull path). Verified in headless Chromium (Playwright): all three views, add-agent flow, duplicate-name error, live SSE board updates w/o reload; zero console errors. `make demo` now points at the browser. 72 tests green. |
| 4 — Supervision gate in the UI | ✅ implemented & approved | 2026-08-20 | Gate view (`#/gate`): all pending messages across lines, note input + approve / return-to-sender / reject per card, line link; same controls inline on pending bubbles in the line view. Mode dial clickable from board cards and the line header (pill = toggle). Release button in the line view when awaiting_reply (confirm dialog; system entry logged). "Something awaits you": amber count badge on the Gate tab + tab title "(N) Agent Courtyard", SSE-driven. Note inputs survive live re-renders (value+focus preserved). Backend: approve-with-note now delivers the note to the recipient as an `operator_note` threaded to the approved message (D7 "add, not edit"). Puppet ScriptBehavior: steps take `kind:` (react to system notices — e.g. revise-and-resend after a return; back off after a reject) and `to:`; `last_peer` fallback target. Demo: `make demo` phase 2 = gated dev↔ops pair the architect judges in the browser (return→scripted revision, reject→scripted retreat, mode flip mid-conversation). Browser-verified end-to-end via Playwright (return→revise→approve-with-note→operator note delivered→mode flip→release), zero console errors; badge-at-zero CSS bug caught and fixed. 77 tests green. Gate body-edit (D7 stretch): NOT built — decide at this checkpoint whether the note flow suffices. |
| 5 — Operator as participant | ✅ implemented & approved | 2026-08-20 | **No-gate invariant enforced in the hub**: any line with a human participant is forced to auto_pass on send (self-heals old rows); `set_mode` on operator lines → 403. New unauthenticated operator endpoints (WebUI = the operator's tunnel, D3): `POST /api/operator/send` (compose; normal turn rules), `GET /api/operator/inbox` (non-consuming history read, newest first). Note target extended: `"both"` (now the default) inserts one targeted copy per participant; notes rejected on operator's own lines (403 — send instead). UI: "message an agent…" compose panel on the board (targets labeled with liveness, connected first — dead-cast confusion found in testing); message composer on operator lines (turn-aware: shows "waiting for X" when the peer owes the reply; Ctrl/Cmd+Enter); note composer w/ target select (both/a/b) on inter-agent lines; Inbox view + blue unread badge (locally-tracked last-seen; viewing marks seen) + combined tab-title count; operator lines show "no gate" instead of the mode dial. Composer-clear race with SSE re-renders found via screenshot and fixed (clear by stable field id, not element ref). Demo phases updated (browser compose → inbox; note-to-both into the gated pair, verified in both puppet logs; `PYTHONUNBUFFERED` so logs tail live). Browser-verified via Playwright; 84 tests green (7 new in test_operator_api.py). **Approving this step = hub + UI done for v1.** |
| 6 — Claude Code adapter + invite + launch | 6a spike ✅ · 6b adapter ✅ · 6c hub-side contract ✅ (D14, no Stop hook) · **6d install ✅ (D15, token inline)** · 6e–6f next | 2026-08-20 | **6d (install):** the hub writes a claude-code agent's `.mcp.json` into its workdir so the operator never hand-edits — merge with any existing file, `.courtyard-bak` backup, other servers/keys preserved, `chmod 600`, reversible. One core (`hub/core/install.py`), two front doors: `POST /api/agents/{id}/install` + `/uninstall` (the WebUI "write .mcp.json into <workdir>" button, dev mode — the hub must share the workdir's disk) and the `courtyard-invite` CLI (thin client over the same endpoint; `--register` create-and-install, `--remove` revert). The hub never stores the plaintext token, so install is handed it and verifies it belongs to the agent before writing. **Token placement decided (D15): inline + chmod 600** — chosen over `${VAR}` expansion and a separate token file, because the hub can't reproduce the token so any external-secret scheme means re-supplying it every launch; the commit risk is met with a "do not commit" warning, not by editing `.gitignore`. 14 new tests (119 total): install core against tmp dirs (merge/backup/0600/malformed-refusal/reinstall + all uninstall paths) and 4 API tests (writes file, rejects a foreign token without writing, no-workdir error, install→uninstall round-trip). Runbook entry + `scripts/runbook/install_mcp_json.py`. `make lint` clean. **6c (D14):** the architect's step-back before building the Stop hook — minimise what is installed agent-side, put the rest in the hub, surface blue-moon failures to the operator. The envelope moved from the Claude adapter into hub core (`hub/core/envelope.py`) and ships as `Message.rendered` on every channel push and inbox pull (absent on operator-facing reads); peer discovery moved too (`hub/core/peers.py` + `GET /api/agents/{id}/peers`: reachable first, trimmed at 25, worded for the model; the attach roster uses the same ranking). The adapter lost `wrapping.py`, the liveness sort and the peer limit, and now forwards text. Tests: envelope suite moved to `test_envelope.py` with a real break-out attempt added; delivery tests assert the envelope on push and on pull and its absence on operator reads; four peers API tests (own-token only, self/removed excluded, ranking, trim). 105 tests green, `make lint` clean. The Stop hook is recorded as verified-not-adopted (D-spike, D14) and the 6a spike stays as the record. **6b:** `courtyard-claude-mcp` (`src/courtyard/adapters/claude_code/`) — one stdio MCP server per agent that is channel + toolbox + hub adapter at once. Declares `claude/channel`, so hub deliveries become live turns; tools `courtyard_send` / `courtyard_inbox` / `courtyard_peers` (peers wires the operator-curated `description` into discovery — the step-1 to-do); attaches after `notifications/initialized` (backlog arrives during attach), heartbeats, re-attaches on `not_attached`, pulls the inbox when a heartbeat reports queued, detaches on stdin EOF. JSON-RPC over stdio hand-rolled — five methods, no MCP SDK, no new dependencies (rationale in design §7.2). stdout is protocol-only, diagnostics to stderr. Hub verdicts (gate hold, turn violation) are surfaced verbatim to the model as tool results. **L0 launch brought forward from 6e so 6b is testable by hand:** `GET /api/config` exposes the adapter's absolute path (Claude Code spawns MCP servers with the *agent's* project as cwd, so the WebUI cannot guess it), and the Agents page gained an agent-type selector — registering a `claude-code` agent now prints its ready-to-paste `.mcp.json` plus the `claude --dangerously-load-development-channels server:courtyard` line, each with a copy button. `wrapping.py` = the **authority-graded envelope** (design §7.5, new), shared with 6c/step 7: trusted/untrusted replaced by a grade the hub derives from the sender's role — `operator` (the human decision maker, note or composed message alike), `domain-owner` (an agent with a declared `sme_domain`: expert on its own ground, petitioner on yours — the envelope names both grounds), `agent` (a peer with no declared ownership: asks, does not order), `hub-notice` (gate verdicts, line state), plus `policy` reserved with no producer in v1 — the grade for a future automated policy
reviewer, ranked deliberately above the operator (post-v1). Delimitation stays uniform: bodies are escaped so they cannot close or forge the envelope. Migration `0005` adds `agents.sme_domain` (short operator-written phrase; overlapping domains are normal and the recipient's model resolves them — the hub does not arbitrate), wired through registry/API/attach-roster/`courtyard_peers`/WebUI (new "owns" column + form field). Messages are enriched with `sender_type`, `sender_sme_domain`, `recipient_sme_domain` — which fixed a real bug: grading by `kind` alone framed the operator's own composed messages on operator lines (§5.6) as peer data. 13 new tests (98 total): envelope framing + break-out attempt, config errors, and a full end-to-end that drives the real adapter process over pipes against a real hub — handshake, tools, gate hold, turn violation, delivery as a channel notification, approve-note as an operator note, backlog-on-attach, detach on EOF. No Claude Code or model tokens needed to prove the surface. **6a (spike, earlier the same day):** docs research first (Claude Code 2.1.237): the experimental capability became the **channels** research-preview feature — MCP stdio server w/ `claude/channel` capability pushes `notifications/claude/channel` events that arrive as live `<channel>` turns; events queue while busy, deliver next turn; custom channels via `--dangerously-load-development-channels`; channels are stdio-only (settles per-agent adapter vs hub-as-MCP-server). Also confirmed: `--name`/`--resume <id-or-name>` (resume keeps session id; `--fork-session` forks), `claude -p --resume` documented (architect's proposed mechanism; concurrency undocumented), Stop hook current field `systemMessage` + 8-consecutive-block override, no wake-idle mechanism exists. Spike kit in `spikes/6a-delivery/` (throwaway): A channel server (bun, smoke-tested), B stop hook (logic verified standalone), C `resume-deliver/deliver.sh`; README = run book + D-spike verdict template. Architect runs the live experiments. |
| 7 — WebUI: quickstart UX (agile) | ⏳ in progress — approved through 7d; **review cycle 1: WP-A + WP-B done and confirmed by the architect; items 9–12 fixed; communications round-trip test green** | 2026-08-24 | **Scope cut (architect, D16):** 6e L1 launch, 6f live mode, and the pi adapter moved out of v1 — v1 is Claude Code only, hub on the host. New step 7 = quickstart-shaped WebUI (7a MainBoard, absorbing Gate + Inbox · 7b Agent Admin · 7c Courtyard Admin, new · further letters from feedback), **agile per page**: design proposal → review → implement → approve. **The quickstart is a permanent product feature (D17, 2026-08-22):** `docs/quickstart.md` — install/start plus the worked example operator → `main-admin` → `infra-claude` — is a v1 deliverable maintained alongside the pages; v1 acceptance = the architect running it as a new operator would, which doubles as the D14 wake-at-turn-end check. **Layout (2026-08-22):** the architect moved from function to style and re-directed the whole UI (ChatGPT-like frame: collapsible side bar, agent rectangles, one input box always at the bottom, lines as two nodes + a colour-coded wire); prototype `ui-designs/layout.html` reviewed and confirmed; framework chosen — **Preact + htm, vendored, no build step (D18)**. Implemented in `webui/`: the frame (rail, top bar, composer on every page), MainBoard (team rectangles, wires with status colours and needs-you ordering, inactive fold, conversation pane with inline gate verdicts that take their note from the bottom box, mode switch + release in the pane header), Agents page ported (row click selects the agent for the box), Admin page with live facts only. Old Gate / Inbox / Line views and `controls.js` removed; per-line "seen" replaces the global inbox-seen. The earlier 7a line-card prototype (`ui-designs/mainboard.html`) is superseded; its content ideas live on in the pane and the wires. Light and dark themes (tokens only; follows the system; switch in the side bar + Admin → Appearance). **Stored tokens (D19, 2026-08-22):** migration `0006` keeps the plaintext beside the hash; `GET`/`POST /api/agents/{id}/token` (read / rotate — rotation revokes the old token at once, drops the channel, agent reads offline until restarted); install and `courtyard-invite` need no token; Agents page: **launch config** (the `.mcp.json` / puppet command, any time) + **rotate token** + remove per row, and a clear "no stored token — rotate" panel for pre-0006 registrations. 5 new tests (124). Runbook: `scripts/runbook/token_rotation.py`. **Try-out feedback round 1 (same day):** Team and Lines became two independently scrolling panels (many agents hid the lines); nav label MainBoard → **Courtyard**, no page title strip, hub dot in the side bar; **agent colours** — migration `0007` (`agents.color`, eight palette names, backfilled round-robin), chosen with swatches at registration or assigned least-used by the hub (`pick_color`), used as the card background and on the agent's name chips (wires, composer, Agents table); `courtyard-invite --color`. 126 tests. **Round 3:** the mode switch is a two-state control in the pane header (supervised | auto-pass, current one filled); Team and Lines panels get drag grips with floors (one card row / two lines / conversation ≥ ⅓ of the page), remembered per browser, double-click to reset. **Archive (D20, same day):** migration `0008` `lines_archive` (one JSON document per archived history); `hub/core/archive.py` — on request (`POST /api/lines/{id}/archive`: line continues empty + idle, system entry), on agent removal (lines archived and dropped), at startup for agents removed earlier; `GET/DELETE /api/archive[/{id}]` + `/export` (JSON download); Archive page in the side bar (list → read-only transcript, export, delete); archive button in the pane header with a confirm that names what goes with it; the inactive-lines fold is gone. 5 new tests. Runbook: `scripts/runbook/archive_line.py`. WebUI files now served with `Cache-Control: no-cache` (a mixed old/new module cache stalled the Archive page on first try). 132 tests. **7d approved by the architect 2026-08-23.** Browser-verified against `make demo` (Playwright, zero console errors). **Quickstart doc:** first draft written against today's pages (Board · Gate · Inbox · Agents); hub-side steps (install, register, `.mcp.json` written, revert) verified against a live hub; the Claude Code launches are the architect's to run. Re-checked as each page lands. **Review cycle 1 (2026-08-23/24):** the architect's acceptance testing with two real Claude Code agents produced 12 feedback items → `docs/planning/feedback-items.md` (stated first, then discussed and grouped into work packages WP-A…WP-E; duplicates merged). Done the same day, per his direction, then paused for his review: **WP-B** gate-note UX (while a message is held, the input box *is* the verdict's comment — amber "gate comment" chip, Enter and ↑ send nothing, the text leaves only with approve / return / reject, whose strip now names both directions; the hub already routed approve-notes to the recipient and return/reject comments to the sender, so this is WebUI-only; with nothing held the note target is a visibly clickable `note → both ▾` control; `reject` keeps its name — architect's call) and **WP-A** agent-side profile (**D21**: install also writes `.claude/settings.local.json` — the `mcp__courtyard` allow rule so sends never halt on a terminal permission prompt, the agent's declared model — `agents.model`, migration `0009`, a form field, `--model` in the suggested launch command — and a status line naming the agent, set only when none exists; uninstall removes exactly what install added, the model stays; settings facts verified against the Claude Code docs). 141 tests; runbook install script extended and green; both flows browser-verified (Playwright, zero console errors). WP-C (answer-only etiquette), WP-D (add-agent form layout) and WP-E (manual links — design proposal first) await his review. **Same evening, from his live testing (items 9–12, all fixed and confirmed):** release valve shown on the operator's own lines; per-selection drafts; item 10 analysis recorded (turn obligations vs ephemeral sessions — remedies R1–R3 proposed, his call pending); the Claude Code channels preview drifted twice (2.1.241 broke `--dangerously-load-development-channels`, 2.1.245 restored it and broke the two-flag workaround) — original flag kept, D-spike note updated; adapter attach now retries forever (agents-before-hub works; e2e test). New **communications test**: `tests/communications/oper-agent1-oper.py` + `communication-test-config.yml` + `make test-comms` — operator → agent1 (live Claude Code, haiku, pty, auto-consent) → operator, with failure diagnostics (message status, channel registered/skipped, screen tail); PASS on 2.1.245 and confirmed by the architect. 142 tests. |

---

## Step 0 — Skeleton and harness (S)

**Goal:** a runnable, testable empty project.

- `git init` + first commit (design + planning docs, layout per design §12).
- `pyproject.toml` (Python 3.12+, FastAPI, uvicorn, pydantic, psycopg 3, pytest, httpx for
  tests; ruff for lint), `Makefile` (`run`, `test`, `lint`, `db-up`, `db-down`), `.gitignore`.
- `docker-compose.yml` with the postgres service (named volume) — dev mode per design §9.4.
- Migration runner + migration `0001` (agents/lines/messages/channels schema per design
  §9.3), applied at hub startup.
- `courtyard-hub` starts, binds `127.0.0.1:2626` (default port — configurable), connects to
  `DATABASE_URL`, serves `GET /api/health` (reporting DB connectivity) and a placeholder
  WebUI index page.

**Demo:** `make db-up && make run` → browser shows "Courtyard hub is alive";
`curl :2626/api/health` → `{ok, db: ok}`.
**Tests:** health endpoint incl. DB status; migrations apply idempotently (run twice);
refuses non-localhost bind without override flag.
**UX checkpoint:** trivial — architect confirms the repo layout and tooling feel right.

---

## Step 1 — Core domain over HTTP: registry, lines, turns, gate (M)

**Goal:** the entire domain model working and enforce-tested — API-only, no UI, no delivery
pushes yet.

- Storage: repository interfaces + the Postgres backend (plain SQL, transactions); message
  persist and the line-state transition commit as **one transaction** (design §9.2). An
  in-memory fake repo serves the pure turn-machine unit tests; integration tests run against
  the compose postgres.
- Agent registry: create ("invite"), list, get, remove; name→UUID index with hard-fail on
  unknown/ambiguous names; per-agent bearer tokens enforced on agent-scoped endpoints.
  Operator agent auto-created on first run.
- Lines: auto-create on first send; mode (`supervised`/`auto_pass`, default supervised);
  mode toggle endpoint; release endpoint.
- Messages + **turn-taking state machine** exactly per design §5.4, including synchronous
  machine-readable turn-violation errors.
- **Gate** with the pluggable `Approver` interface; decisions via
  `POST /api/gate/{message_id}` (approve / **return** / reject + note); return and reject
  keep the message in history (`returned` / `rejected`) and send the sender a `system`
  notice carrying the comment (design §5.4 rule 4).
- `operator_note` and `system` kinds, turn-exempt.
- Delivery in this step = messages become readable via `GET /api/agents/{id}/inbox` (the pull
  path); channel push comes in step 2.

**Demo:** a documented `curl` walkthrough (`scripts/step1-walkthrough.sh`): invite two agents,
send a→b on a supervised line, see it pending, approve it, reply, hit a turn violation, return
a message to its sender with a comment, reject another, release a line.
**Tests (the dense ones):** unit tests on the turn machine covering every transition and every
illegal move; gate approve/return/reject with notes; auto-line-creation; name hard-fail;
token auth; postgres repo round-trip; send/gate/state-transition atomicity; inbox pull with
`after=seq`.
**UX checkpoint:** architect reviews the API shapes and the walkthrough output — this is the
protocol he'll live with; cheaper to rename/reshape now than after the UI exists.

---

## Step 2 — Delivery push + puppet agents (M)

**Goal:** live end-to-end conversations between processes — the courtyard actually *works*,
still with no UI.

- `deliver()` per design §6.1: persist → SSE event (stream exists, UI consumes it next step)
  → HTTP push to registered channel endpoint with channel token → stale-marking on failure.
- Channel registry: attach/detach endpoints, heartbeats, liveness states
  (`invited/connected/stale/gone`).
- Shared hub client library (`courtyard.common.client`) — the adapter contract implemented
  once.
- **Puppet agent** (`courtyard-puppet`): registers, attaches with its own little HTTP listener,
  receives pushes, replies per behavior: `echo`, `script:<yaml>` (match/reply/delay), `manual`
  (human types replies in the puppet's terminal).
- Reconnect semantics per design §6.4: attach summary (active lines, whose turn, in-flight
  message), channel replacement (last attach wins), re-delivery of the `queued` backlog in
  order — proven by killing a puppet mid-conversation and restarting it.

**Demo:** `make demo` → hub + two scripted puppets; a multi-turn conversation runs
autonomously on an auto-pass line and is visible via the API/walkthrough script; then the
same with one puppet in `manual` mode — the architect *is* one of the agents from a second
terminal.
**Tests:** integration over real HTTP: two puppets full conversation; supervised line holds
until an API-approve releases it; turn violation surfaced to the puppet as an error; kill/
restart re-delivery of the `queued` backlog; attach-summary correctness; a second attach
replaces the first channel; channel-token rejected when wrong; heartbeat → stale transitions.
**UX checkpoint:** architect runs the demo, plays a manual puppet, approves the *feel of the
message flow* before any pixels exist.

---

## Step 3 — WebUI: live board monitoring + agent admin (M)

**Goal:** first real UI — watch the courtyard live; manage the registry. Read-mostly.

- Static frontend (vanilla ES modules, no build step) served by the hub; SSE wired for live
  updates.
- **Board view**: lines with liveness badges, mode indicator, unread/pending counters.
- **Line view**: full chat history rendering all kinds (messages, notes, system, rejected
  greyed out), updating live.
- **Agents view**: list with status; add agent (creates registration, shows the copy-paste
  launch command for puppets at this step); remove agent.
- Visual design: clean and minimal; enough polish that UX judgment is possible.

**Demo:** run the step-2 demo, watch two puppets converse **live in the browser**; add a third
puppet from the UI (copy-paste its launch command), watch it appear and join a conversation.
**Tests:** API-level tests for everything the UI calls (the UI itself is exercised manually at
this stage; UI test automation via Playwright is a later, optional add).
**UX checkpoint — the big first one:** this is the architect's first *feel* of the product.
Expect layout/flow feedback; fold it in before step 4.

---

## Step 4 — Supervision gate in the UI (M)

**Goal:** the human-in-the-loop dial — the heart of the project — fully usable.

- Mode toggle (auto-pass ⇄ supervised) per line, from board and line views.
- **Gate queue view**: all pending messages across lines; approve (+ optional note that is
  delivered as an operator note), **return to sender** (+ comment), reject (+ note); inline
  gate controls in the line view too.
- Pending messages visually distinct in line history; SSE-driven "something awaits you"
  indicator (browser tab badge/title).
- Line release action in the UI.
- Stretch (only if step-4 UX demands it, per Decision D7): edit-body-before-delivery.

**Demo:** scripted puppets on a supervised line; the architect approves / annotates /
returns-with-comment / rejects their conversation in the browser and flips the line to
auto-pass mid-conversation; a puppet scripted to resend a revised message after a return.
**Tests:** gate flows over the API (pending→approve→delivered with note attached;
pending→return→sender notice with comment, then a revised resend passes; pending→reject→
system notice; mode flip mid-flight; release while pending).
**UX checkpoint:** the supervised workflow — is the dial in the right place, is approving
fast enough, does the note flow match "add, not edit"?

---

## Step 5 — Operator as participant (M)

**Goal:** the operator stops being only a supervisor and becomes a peer on the board.

- Operator-initiated conversations: compose to any agent from the UI; `operator↔agent` lines
  with normal turn rules, no gate; replies surface in an **operator inbox** view + SSE
  notification.
- **Insert into an inter-agent line**: operator note composer in the line view, target a / b /
  both (default both).
- Turn-state visibility polish: line views clearly show whose turn it is / what's blocking.

**Demo:** architect starts a conversation with a scripted puppet from the browser; then, while
two puppets converse, drops a clarification note into their line and sees both puppets receive
it.
**Tests:** operator line turn rules; note targeting (a/b/both) delivery; operator inbox pull;
no-gate-on-operator-lines invariant.
**UX checkpoint:** full human-in-the-loop loop — supervise, correct, converse — with fakes.
**Approving this step means the hub + UI are done for v1**; everything after is adapters.

---

## Step 6 — Claude Code adapter + invite + launch (L)

**Goal:** real agents in the courtyard.

- **6a. Spike (do first; can start any time after step 2):** minimal MCP stdio server proving
  turn delivery via the `claude/channel` capability on the current Claude Code version.
  Outcome recorded in the design doc's decision log (D-spike). Fallback if dead: Stop-hook-only
  delivery.
- **6b. MCP server** (`courtyard-claude-mcp`): tools `courtyard_send` / `courtyard_inbox` /
  `courtyard_peers`; attach-on-start via env; channel endpoint with token; the
  authority-graded envelope on every delivery (design §7.5).
- **6c. Hub-side delivery contract** (design D14; replaces the Stop hook): the hub renders
  the envelope (`Message.rendered`) on pushes and inbox pulls, and
  `GET /api/agents/{id}/peers` returns peers ranked, trimmed and worded; the Claude adapter
  becomes a forwarder. **No Stop hook in v1** — reasons in D14; delivery-health banners
  (offline with mail, unanswered too long) belong to the WebUI pass after step 6.
- **6d. Install** (was: invite installer) ✅: hub-side "write `.mcp.json` into the workdir"
  (merge with backup, revert) so the operator never hand-edits, via the WebUI button and the
  `courtyard-invite` CLI over one core. Token placement resolved — inline + `chmod 600` (D15).
- ~~6e. Launch L1~~ · ~~6f. Live mode~~ — **moved out of v1** (architect,
  2026-08-20, the step-7 scope cut / D16): L0 — the copy-paste command plus 6d's install
  button — is all the quickstart needs, and v1 runs the hub on the host (`make run`).

**Demo (staged):** (1) one real Claude Code agent talks to a scripted puppet through a
supervised line; (2) **two real Claude Code agents** — e.g. a coding agent and an infra agent
in different directories — collaborate on a small real task through the courtyard, with the
architect supervising one line from the browser. This scenario is now run through step 7's
quickstart, which is where v1 acceptance lives.
**Tests:** envelope rendering and the break-out attempt (hub-side); peers ranking/trim via
the API; MCP server handlers against a test hub; install writes-then-reverts round-trip on a
temp dir. (The live Claude Code end-to-end stays a scripted-but-manual demo — we don't burn
tokens in CI.)
**UX checkpoint:** real agents work end to end through the hub. Final v1 acceptance — the
architect replacing himself as relay — moved to step 7's quickstart.

---

## Step 7 — WebUI: quickstart UX (v1, agile)

**Goal:** a functional, minimalistic WebUI with intuitive UX, shaped around the **quickstart
configuration**: the operator (WebUI + own terminal) plus a two-agent claude-code team
(`main-admin` and `infra-claude`), each in its own terminal.

**The quickstart is a permanent part of the product (design D17)** — the convenience path a
new operator follows to start using the courtyard for day-to-day work, not a demo. Three
parts, all shipping with v1:

1. **Easy install and start** — clone, `uv sync`, `make db-up && make run`, open the browser.
2. **One worked example** — register `main-admin` and `infra-claude`, let the hub write
   their `.mcp.json` (6d), start each in its own terminal; the operator messages
   `main-admin` from the WebUI, `main-admin` asks `infra-claude` something simple (list the
   files in your directory), the operator approves the inter-agent message at the gate and
   reads the answer.
3. **The document** — [`docs/quickstart.md`](../quickstart.md): the two above, written for
   someone who has never seen the project. Drafted against today's pages and re-checked as
   each step-7 page lands; a page is good when a new operator gets through it unaided.

**v1 acceptance** = the architect running the quickstart as a new operator would (ground rule
7). That run doubles as the D14 wake-at-turn-end check (design §14 risk 3).

**Working mode: agile, not waterfall** (architect, 2026-08-20). Per page: design proposal (a
static prototype in `ui-designs/`, nothing wired) → architect review → implement → approve.
No up-front plan beyond the page list; letter-items are added from architect feedback as we
go.

- **7-layout** — the frame everything lives in (design §10, D18): collapsible side bar,
  one input box at the bottom of every page, MainBoard = team rectangles + wires +
  conversation pane. Implemented 2026-08-22 on Preact + htm; awaiting the architect's
  try-out — feedback becomes the next letters.
- **7a. MainBoard** — the daily page. Absorbs the standalone Gate and Inbox pages (gate
  decisions and the operator's own conversations are the board's business, not separate
  destinations). First design (line cards, approved 2026-08-20) superseded by the layout
  above; what survives: inline gate verdicts, delivery health as quiet text, inactive fold,
  needs-you-first ordering.
- **7b. Agent Admin** — registration, install (6d), launch command, removal. First slice
  landed 2026-08-22 with D19: per-agent **launch config** (re-openable; the hub keeps
  tokens), **rotate token**, remove.
- **7d. Archive** (architect's ask, 2026-08-22, D20) — archive on request and on removal;
  Archive page. Landed the same day; **approved 2026-08-23**.
- **7c. Courtyard Admin** — the courtyard itself (new page): housekeeping such as clearing
  dead registrations (their lines are archived by D20 already), defaults such as supervision
  mode, health.
- *(further letters from architect feedback)*

The deferred delivery-health surfacing (offline with mail; unanswered too long) lands
wherever this step's design puts it — 7a's approved design puts it on the line card.

---

## Step → design traceability

| Step | Proves out (design §) |
|---|---|
| 0 | §4 process model, §9.2–9.4 storage + dev mode, §11 binding |
| 1 | §5 domain model, §5.4 turn machine, §5.5 gate, §9 storage |
| 2 | §6 delivery, §6.2–6.4 channels/liveness/reconnect, §7.1 adapter contract, §7.4 puppet |
| 3 | §10 WebUI (board/line/agents) |
| 4 | §10 gate queue, D6/D7 |
| 5 | §5.6 operator-as-participant |
| 6 | §7.2 Claude adapter, §8 launch L0 (D8), §14 risk 1 spike |
| 7 | §2 goal 8 + D17 (quickstart as product); §10 layout + D18 (Preact + htm); MainBoard absorbs gate+inbox; Courtyard Admin new; v1 acceptance |
