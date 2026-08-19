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
   The turn machine and gate — the core — get the densest coverage (the ai-maestro
   zero-tests-on-core mistake, inverted).
5. Steps are small on purpose. Rough effort marks (S/M/L) are relative, not calendar promises.

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
  turn-injection via the `claude/channel` capability on the current Claude Code version.
  Outcome recorded in the design doc's decision log (D-spike). Fallback if dead: Stop-hook-only
  delivery.
- **6b. MCP server** (`courtyard-claude-mcp`): tools `courtyard_send` / `courtyard_inbox` /
  `courtyard_peers`; attach-on-start via env; channel endpoint with token; untrusted-content
  wrapping on every injection (design §7.2).
- **6c. Stop hook** (`courtyard-claude-hook`): block-on-unread with `stop_hook_active` +
  seen-id dedup.
- **6d. Invite installer** (`courtyard-invite`): registers agent, writes project-level
  `.mcp.json` + `.claude/settings.json` hook config (merge with backup), prints launch
  command; `--remove` reverts cleanly.
- **6e. Launch**: L0 (copy-paste command in UI) + L1 (macOS `osascript` terminal spawn from
  the UI); "connected" flips on the attach handshake.
- **6f. Live mode**: hub `Dockerfile` + compose profile `live` (hub and postgres in
  containers, hub published on `127.0.0.1:2626`); agents/adapters stay on the host in the
  operator's terminals and use the published port. `make live-up` / `make live-down`.

**Demo (staged):** (1) one real Claude Code agent talks to a scripted puppet through a
supervised line; (2) **two real Claude Code agents** — e.g. a coding agent and an infra agent
in different directories — collaborate on a small real task through the courtyard, with the
architect supervising one line from the browser. This demo *is* the v1 acceptance scenario.
**Tests:** unit tests on hook decision logic (loop safety, dedup) and MCP server handlers
against a test hub; invite installer writes-then-reverts round-trip on a temp dir; injection
wrapping. (The live Claude Code end-to-end stays a scripted-but-manual demo — we don't burn
tokens in CI.)
**UX checkpoint = v1 acceptance:** the architect replaces himself as relay on a real
two-agent task.

---

## Step 7 (v1.1) — pi-coding-agent adapter (M, later)

TypeScript extension implementing the same adapter contract (attach / send tool / inject /
heartbeat / detach) against the unchanged hub API — the proof that the tunnel seam is truly
pluggable. Scoped in detail only after step 6 experience; tracked here so it stays on the map.

---

## Post-v1 parking lot (explicitly not now)

- Orchestrator-agent approver behind the `Approver` interface (design D10).
- Ed25519 read-time verification if agents ever span machines (design D3).
- Memory subsystem (ai-maestro review borrow-list: jsonl indexing, local embeddings,
  extraction prompt + dedup-with-reinforcement).
- tmux launch option L2; Linux L1 spawn; Playwright UI test automation; body-edit at gate if
  step 4 didn't already force it.

## Step → design traceability

| Step | Proves out (design §) |
|---|---|
| 0 | §4 process model, §9.2–9.4 storage + dev mode, §11 binding |
| 1 | §5 domain model, §5.4 turn machine, §5.5 gate, §9 storage |
| 2 | §6 delivery, §6.2–6.4 channels/liveness/reconnect, §7.1 adapter contract, §7.4 puppet |
| 3 | §10 WebUI (board/line/agents) |
| 4 | §10 gate queue, D6/D7 |
| 5 | §5.6 operator-as-participant |
| 6 | §7.2 Claude adapter, §8 launch (D8), §9.4 live mode, §14 risk 1 spike |
| 7 | §7.3 pi adapter — pluggability of §7.1 |
