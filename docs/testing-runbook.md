# Manual execution of Test Suite

Manual procedures for exercising the system by hand — the counterpart to the automated
suite (`make test`). Each entry: what it proves, a copy-paste command, and what you should
see.

**Prerequisites for every procedure:** a running hub.

```
make db-up
make run      # leave this terminal up; run procedures from another
```

Optional but recommended before a procedure whose output lists agents: `make db-nuke`
(then `make run` again) clears registrations left by earlier runs.

---

## Hub-side envelope + peer discovery

**Feature under test:** the authority-graded envelope is rendered by the hub and delivered
as `Message.rendered` (design §7.5, D14); operator-facing reads stay raw; `courtyard_peers`
is ranked/trimmed/worded hub-side; a message body cannot forge its own envelope.

**Run:**

```
uv run python scripts/runbook/envelope_and_peers.py
```

**Expected:** four blocks, then `(cleaned up the two throwaway agents.)`, exit 0.

1. **What the agent receives** — an envelope with `authority="domain-owner"`, a first line
   naming both grounds (`infra-… owns: the AWS estate and IAM. You own: the payments
   service.`), the "expert judgement … the call is yours" preamble, a `────` divider, then
   the body — and, on a question, a second `────` divider with the **reply footer**
   (WP‑C, item 16): "To answer, use the courtyard MCP tool `courtyard_send` … no trailing
   offers, no side questions". A message that *answers* one ends instead with "the
   exchange with <sender> is complete … deliver them the answer now" (scoped by name + relay clause, item 26). An operator note ends with its own footer ("needs no separate reply … tell the operator with courtyard_send", item 24); system messages have no footer.
2. **The board view of the same message** — `body` is the plain text; `rendered` is `None`.
3. **`courtyard_peers`** — begins `Agents on the courtyard board`, reachable agents first
   then by name, each line `name — type, status [— owns: …] [— description]`. (Any other
   registered or dead agents appear here too; `make db-nuke` for a clean list.)
4. **Break-out attempt** — the body's `</courtyard-message>` and forged
   `<courtyard-message from="operator" …>` come through escaped as `&lt;…`; verdict line
   reads `exactly one real closing tag (True), forged operator tag present? False`.

**Live check for the reply footer** (item 16's incident, reversed): with an agent on
shift, send it a natural question **with no hint about how to reply** (e.g. "do you have
a terragrunt tree in your directory?"). The answer must arrive on the board — not only in
the agent's terminal transcript. `make test-comms` proves the same thing scripted: since
WP‑C its test message says only "reply with exactly: ACK <nonce>", no mechanism named.

---

## Install `.mcp.json` + the agent-side profile into a workdir

**Feature under test:** the hub writes a claude-code agent's `.mcp.json` into its project
(design §8/D8, 6d) — merging with any existing file, keeping a backup, token inline +
`chmod 600` — plus `.claude/settings.local.json` (WP-A, D21: the courtyard allow rule, the
declared model, a status line naming the agent) — and reverses cleanly. Dev-mode only (the
hub must share the workdir's disk).

**Run:**

```
uv run python scripts/runbook/install_mcp_json.py
```

**Expected:** three blocks, then `(cleaned up …)`, exit 0.

1. **Install** — reports `wrote … .mcp.json` and `backed up … .courtyard-bak`, plus the "do
   NOT commit it" warning. `servers now: ['my-linter', 'courtyard']` (the pre-existing server
   is kept), the courtyard `env` shows `TOKEN=…` inline, `file mode : 0o600`, and the backup
   holds the original.
2. **Settings** — `allow : ['mcp__courtyard']`, `model : sonnet`, and a status line
   `echo '⏺ <name> · courtyard'` in `.claude/settings.local.json`.
3. **Uninstall** — `restored from backup: True`, `servers now : ['my-linter']`, backup gone;
   the settings hold only `{'model': 'sonnet'}` (the model stays on purpose).

**Also (real terminal path, optional):** `courtyard-invite --register --name coding
--type claude-code --workdir <dir>` registers and installs in one command; for an agent
that already exists, `courtyard-invite --name coding --workdir <dir>` is enough (the hub
keeps the token, D19); add `--remove` to revert. Needs `uv sync` first so the
`courtyard-invite` entry point exists.

---

## Stored tokens: read back, rotate

**Feature under test:** the hub keeps each agent's token (design D19): it can be read
again, install needs none passed in, and rotation revokes the old token at once and drops
the agent's session.

**Run:**

```
uv run python scripts/runbook/token_rotation.py
```

**Expected:** four blocks, then `(cleaned up …)`, exit 0.

1. **Read it back** — `same as at registration? True`.
2. **Install without passing a token** — `equals the stored one? True`.
3. **Rotate** — `status before: connected`, `different from the old one? True`,
   `status after : gone`, `old token : refused (… invalid_token …)`, `new token : inbox
   read OK -> []`, `read back` shows the new one.
4. **Re-install** — `replaced the courtyard entry: True`, `… equals the new token: True`.

---

## Archive: on request, on removal, read back, export

**Feature under test:** a line's history becomes one immutable document (design §5.7,
D20): archived from the pane header (line continues empty and idle), archived by itself
when an agent is removed (its lines leave the board), readable and exportable on the
Archive page.

**Run:**

```
uv run python scripts/runbook/archive_line.py
```

**Expected:** three blocks, then `(cleaned up …)`, exit 0.

1. **Archive on request** — `reason : operator   messages: 3`; `line now : 1 entry ->
   [system] history archived by the operator (3 messages)`; `line state : idle`.
2. **Read it back + export** — the transcript lists the three bodies, `gate note kept:
   'fine by me'`, `export : HTTP 200, attachment; filename="courtyard-…json"`, `same
   document: True`.
3. **Removal archives by itself** — `line still on the board: False`; two archives for
   the removed agent, newest first: `[('agent_removed', 2), ('operator', 3)]`.

**In the browser:** with a line selected, **archive** in the pane header asks first (and
says so if the line is released or messages go undelivered); afterwards the pane shows
one system entry and the **Archive** page (side bar) lists the conversation — click it to
read it, **export JSON** downloads it, **delete** removes it after a confirm. The input
box reads *Archived conversations are read-only* on that page. Removing an agent on the
Agents page makes its lines vanish from the Courtyard page and appear in the Archive.

**In the browser (Agents page):** every agent row has **launch config**, **rotate token**,
**remove**. *launch config* opens the `.mcp.json` (or dummy command) with the token and
the install button — close and open it again, same content. *rotate token* asks first,
then opens the config with the new token and a "Token rotated" note; the agent's dot goes
grey until it is restarted with the new file. An agent registered before migration 0006
gets a "no stored token" panel with a rotate button instead.

---

## Communications round trip: operator → agent1 → operator (live Claude Code)

**Feature under test:** the whole production delivery path with a real Claude Code
session — hub, install, attach, channel push into a live turn, `courtyard_send` reply.
This is the first thing to run when "messages stop arriving" (feedback items 10/11):
its failure output separates every class we have seen — hub-side (`queued`), adapter
ACK with the session skipping events (`delivered` + "Channel notifications skipped"),
or the model simply not replying (screen tail).

**Run** (needs a registered claude-code agent with a workdir; spends a few model tokens —
cheap model by default; the hub is started for you if none is running):

```
make test-comms
```

Defaults live in `tests/communications/communication-test-config.yml` (hub, agent1,
model, timeout); CLI flags on the script override the file:
`uv run python tests/communications/oper-agent1-oper.py --agent … --model …`

**Expected:** blocks 0–3, then
`PASS — full round trip: operator -> hub -> channel turn -> courtyard_send -> operator`,
with `test message status: delivered` and a reply echoing the nonce (`ACK <nonce>`).
The launcher answers the dev-channels consent dialog by itself; a stuck operator line
from earlier testing is released automatically first.

**On FAIL, read the three diagnostics:** the message status, the channel verdict from
Claude Code's own MCP log ("registered" is healthy; "skipped: …" names the reason — the
launch-flag contract has drifted across Claude Code updates before), and the last lines
of the agent's terminal.

---

## Shift + Team mode: one pill starts and ends the team (design §8.1, D23)

**Feature under test:** the shift state machine (off → starting with grace countdown →
on → off), the Team-mode/terminal-app settings, and the real terminal spawning.

**Scripted part** (settings round trip, `always_on` refused, custom terminal apps
added/validated/removed (item 20), the machine through a full cycle — spawns nothing: the throwaway agent is a dummy, and it refuses to run the shift
if real claude-code agents are down):

```
make run                        # hub in another terminal
uv run python scripts/runbook/shift_and_settings.py
```

**Manual part — the real spawn** (his live check; opens actual windows):

1. With one claude-code agent's terminal closed, press **▶ Start shift** on the
   Courtyard page. Expect the amber countdown (`Waiting for the team · N`, ticking —
   it always runs since D28: stored liveness re-verifies before anything spawns, and
   agents show gray "checking…" dots meanwhile) — then exactly one terminal window
   opens (Admin → Team chooses Terminal or iTerm2), already in the agent's workdir
   with the launch command running; the pill shows `Starting · x/y` and flips to
   `● y/y on shift` as cards go green. An agent that proves itself with a heartbeat
   during the countdown turns green and gets **no** window.
2. Press **■ End shift** (the square button beside the status pill) → "End the shift?"
   confirm → **every** window the shift opened closes, even when its agent was
   mid-conversation moments before (the hub waits for each window's processes to end
   before closing, escalating TERM → KILL); terminals you opened by hand stay. With a
   line mid-conversation, expect the second confirm ("N lines are mid-conversation…")
   before anything closes.
3. **D28 (item 31):** End the shift, then press Start again right away, while the dead
   agents' cards are still green (stored status). Expect their dots to gray to
   "checking…" for the countdown and fresh windows to open for them — before D28
   their stale green made start skip them, nothing opened, and the stale-shift
   question fired minutes later.
4. Admin → Team: `Always on` is visibly disabled; switching the terminal app persists
   across a hub restart.
5. **Cold start (item 23):** quit Terminal.app entirely, then Start shift with N agents
   down → exactly N windows open, no extra bare shell (the first agent runs in the
   window Terminal opens at launch); End shift closes all N.

**Expected everywhere:** nothing the shift did not open is ever closed, and a running
agent is never spawned a second time (no "two sessions may be claiming this identity"
system entries after shift starts).

---

## End shift closes the books; incidents re-deliver (design §8.1, §6.4, D24)

**Feature under test:** ending the shift releases every non-idle line and marks the
unfinished messages `expired` (kept in history, nothing deleted); a message delivered to
a previous session and never answered is re-armed and redelivered on the agent's next
attach (R1); the board shows who owes the operator a reply (R3).

**Scripted part** (both halves against a live hub; skips the end-shift half unless every
other line is idle and no real claude-code agent is down — a forced end would expire
real conversations, and a shift start would open real terminals):

```
make run                        # hub in another terminal
uv run python scripts/runbook/expire_and_rearm.py
```

**Manual part:**

1. Send a message to an agent and let it answer with a question of its own, so the line
   waits on **you**: the pane header over your conversation reads "waiting for your
   reply" and the agent's card shows **no** badge. Answer, ask something new, and don't
   let it reply: the card now shows the amber **owes you a reply** badge and the header
   names the agent.
2. Press **■ End shift** while that question is unanswered. Expect the second confirm to
   say unfinished messages are closed as expired — accept it. Afterwards: the badge is
   gone, the line is idle, and the conversation shows the old message struck through
   with `· expired` plus a system entry "the message awaiting a reply expired at end of
   shift". A message that was **held at the gate** expires the same way (its entry says
   "held at the gate").
3. Start the next shift and message the same agent: the expired question is **not**
   re-delivered — the new day starts clean.
4. R1, the incident path: with a shift on, close an agent's terminal by hand while it
   owes you a reply, then reopen it (launch config) — on attach the unanswered message
   is delivered again to the fresh session, and the line history gains "…delivered to a
   previous session … — redelivered".

---

## The stale shift asks a question (design §8.1, D25)

**Feature under test:** a shift left open (terminals closed by hand, or a reboot) is
detected — shift on, liveness grace passed, nobody connected, no window's tty alive —
and the Courtyard page asks what to do instead of silently claiming `0/2 on shift`.

**Scripted part** (its own throwaway hub + scratch database — never the dev hub; seeded
dead-tty window refs, so nothing real ever opens):

```
make db-up
uv run python scripts/runbook/stale_shift.py
```

Expect: right after start the agent reads **`unknown`** with `checking_until` set and
stale `False` (D26 — no claims while the hub verifies); after the grace, ONE transition:
agent `gone` and stale `True` together. A connected agent means not stale; End shift
resolves it; resume with nothing open is refused (`no_shift`).

**Manual part** (the real morning; opens actual windows):

1. With a shift running, close every agent terminal by hand (⌘Q the terminal app is
   fine) and stop the hub. Start the hub again and open the Courtyard page: first the
   **checking phase** (D26) — gray pulsing dots with "checking…", the Team panel
   dimmed, the pill counting `Checking the team · 10` — with **no** green dots and
   **no** question; then, in one transition, the statuses turn offline and the question
   appears — "The last shift was never ended". **■ End shift** is the focused button;
   "Not now" (or Esc / a click outside) leaves the amber *shift left open* tag, which
   reopens the question on click.
2. **Resume lives on the running pill** (the dialog offers only End / Start new): with
   the shift running, close ONE agent's terminal by hand and wait for its card to go
   offline — the pill reads `1/2 on shift` and **`▶ Resume shift`** appears beside
   `■ End shift`. Press it: one terminal opens for exactly that agent (the healthy one
   is untouched), the shift keeps its original start time, and anything the returning
   agent still owed arrives in its fresh session ("…redelivered" in the line history).
3. Repeat step 1 (all terminals closed), then **Start new shift** → the old shift's
   unfinished messages show `· expired`, and a brand-new shift starts (fresh terminals,
   new start time).
4. Restart the hub mid-shift with the agents *running*: the question must NOT appear —
   the cards show "checking…" for at most one heartbeat and turn green as the beats
   arrive, each the moment its agent proves itself (never a false green first).

---

## Agents page: edit, remove-with-cleanup, and the Defaults dial (WP-D + 7c)

**Feature under test:** the reworked Agents page (items 4/8/15) — the add form's field
order, the Edit Agent view over `PATCH /api/agents/{id}`, removal that also cleans the
agent's project directory — and Admin → Defaults' `New lines start` setting (7c).

**Scripted part** (throwaway agents + a temp workdir; the settings value is restored):

```
make run                        # hub in another terminal
uv run python scripts/runbook/agents_edit.py
```

**Manual part:**

1. Agents page: **no message box** (it lives on the Courtyard page only, item 20); the
   add form is collapsed behind **+ Add an agent** and, expanded, reads name · type ·
   directory · model · colour on one row, then two multiline boxes (what is it for /
   what does it own). Rows carry **edit** and **remove** only.
2. **edit** on a row opens the Edit Agent view: change the description and colour, save —
   the row and the board card update live; **launch config** and **rotate token** are in
   the same panel. Name and type are shown as permanent.
3. **remove** opens a dialog; with a workdir set, "also clean up its project directory"
   is pre-checked. Confirm → the agent leaves the list, its lines go to the Archive, and
   the courtyard entries are gone from `.mcp.json` / `.claude/settings.local.json` in
   its directory (other content untouched).
4. Admin (item 20): **Status** section (Hub, Courtyard) first, **Settings** (Team,
   Terminal application, Defaults, Appearance) below; every setting is a pulldown, with
   `Always on` a disabled choice; no message box here either.
5. Admin → **Defaults** → set `New lines start` to auto-pass: a message between two
   agents that never talked before flows ungated; an existing supervised line still
   holds its messages. Set it back.
6. Admin → **Terminal application** → **+ add an application** (e.g. name `kitty`, start
   string `kitty --directory {dir} sh -c {command}`): it appears in the pulldown; select
   it and the start string becomes editable, with the caveat that a custom app only
   opens windows (End shift cannot close them); **remove app** falls back to Terminal.
   With a custom app selected, Start shift opens the agents in that terminal.

---

## Discovery auto|manual: the operator wires the team (design §5.8, D22)

**Feature under test:** the courtyard-wide **Discovery** setting — `auto` (today's
behavior: every agent sees every other, lines form on first message) vs `manual`
(agents see and can message only whom the operator has **linked**; a link IS a
pre-created idle line). Unlink archives the history and removes the line; the operator
is exempt in both directions; switching modes migrates nothing.

**Scripted part** (own throwaway hub + scratch database — flipping the setting on the
dev hub would refuse a live agent's sends mid-run):

```
make db-up
uv run python scripts/runbook/discovery_links.py
```

**Manual part** (dev hub, two or three registered agents):

1. Admin → Settings → Team: the **Discovery** pulldown reads `auto`. On the Courtyard
   page the Lines panel has no link control and its empty text speaks of lines forming
   on first message.
2. Flip Discovery to **manual**. The Lines panel grows a small square **+** in its
   bottom-left corner (a help bubble on hover; clicking it expands the two-agent picker —
   item 25), and, when empty, says "link two agents to open a line". Ask an agent to message a peer it has
   no line with: the tool result says it has no line with that peer and that you link
   agents in this courtyard (`not_linked`); nothing lands on the board.
3. `courtyard_peers` from that agent lists only linked peers plus you, and its text ends
   "the operator manages the links".
4. **+ link agents** → pick the two agents → an idle wire appears; its supervision dial
   is the Defaults setting. Now the same ask goes through (gated per the dial).
5. With the linked line selected, the pane header shows **unlink** beside archive.
   Unlink mid-conversation: the confirm names the consequence, the wire disappears, the
   transcript is on the Archive page with reason `unlinked`, and the pair is refused
   again. Plain **archive** on another line keeps its old meaning — history cleared,
   the line (= the link) stays.
6. You still reach everyone and everyone still answers you — no links needed.
7. Flip back to **auto**: the link control disappears and a first message between any
   pair forms its line again. Lines created by hand under manual simply remain.
8. Live sub-team check (the acceptance shape from §5.8): with three agents, wire A–B and
   B–C but not A–C — A and C cannot see or reach each other while both talk to B.

---

## Courtyard page layout: rail, rectangles, wires, pane, one input box

**Feature under test:** the step-7 layout (design §10, D18) on Preact + htm: collapsible
side bar; the team as rectangles; agent-to-agent lines as two nodes + a colour-coded wire;
the conversation pane showing whatever is selected; one input box at the bottom of every
page that addresses the selection and carries the note for gate verdicts.

**Run:**

```
make demo          # hub + scripted dummies; open http://127.0.0.1:2626/ when it says so
make demo-stop     # afterwards
```

**Expected** (in the browser, the Courtyard page):

1. **Team** — one rectangle per demo dummy, each on its own colour (the hub hands out
   the least-used of eight; green dot = connected; `guest-…` hollow, "not started yet");
   the first one is selected (dark outline) and the box at the bottom reads
   `Message <name>…`. Team and Lines are two tinted panels that scroll independently; the
   grip under each drags its height (no smaller than one row of cards / two lines; the
   conversation keeps at least a third of the page), double-click resets, the height
   survives a reload.
2. **Lines** — `dev ↔ ops` with an **amber** wire, *held at the gate*, listed first;
   `alice ↔ bob` **blue**, *new since you looked* (auto-pass, their 6-message exchange).
   Lines of removed agents are not on the board at all — they are in the Archive (D20).
3. **Gate from the pane** (WP-B, reshaped by item 24) — click the amber wire: the pane
   shows `dev ↔ ops` with the **supervised | auto-pass** switch (supervised filled
   amber; clicking auto-pass flips the line and fills green) and the held message
   carrying its verdict **inline**: the message, then a plain square-cornered comment
   field, then **approve / return to sender / drop**, the hint naming all three
   destinations (`approve sends your comment to ops · return sends it to dev · drop
   sends it nowhere`). There is **no box at the bottom while a line is selected** —
   the composer belongs to direct chats only. Type a comment, click **approve**: your
   comment appears in the pane as a note `you → ops`, ops's scripted reply arrives *held
   at the gate* (supervised replies pass the gate too). Click **return to sender** with a
   comment: the message is struck through with `returned to sender: <comment>` and the
   hub's notice to dev follows. Click **drop** with a comment: struck through with
   `dropped: <comment>` on the board, while the hub's notice to the sender carries no
   comment at all.
4. **Your own line** — click the `concierge-…` rectangle, type, Enter: your bubble on the
   right, the echo reply on the left within a second; the box stays enabled. Message
   `alice-…` (scripted, no reply): the box greys out with *waiting for alice to reply — one
   message at a time on a line* — and a **release** button appears in the pane header
   (the valve works on your own lines too, feedback 9); release returns the box. Drafts
   are per selection: text typed for one agent or line never shows under another.
5. **Unread** — with another agent selected, a reply to you shows `N new` on that agent's
   rectangle and the tab title reads `(N) Agent Courtyard`; both clear when you open it.
6. **Frame** — the icon at the top of the side bar collapses it to a strip (remembered
   across reloads); Agents and Admin keep the same box at the bottom; on Agents, clicking a
   row selects that agent for the box, names carry their colour, and the add form offers
   eight colour swatches with the least-used one pre-selected. Zero errors in the browser
   console.
7. **Themes** — with macOS in dark mode the page opens dark; the sun/moon item at the
   bottom of the side bar switches to the other theme and the choice survives a reload;
   Admin → Appearance → "follow the system" returns to the system's theme.

---

## The channel flag and the delivery check (design §6.3, D29/D30)

**Feature under test:** detecting a session that cannot hear the hub. Two layers: the
adapter reports whether its claude session was launched with the channels flag
(item 33 — `absent` raises a board popup + red card foot), and the delivery check
proves end to end that a channel push reaches the model (item 34 — a hub-notice with
a token the model must return via `courtyard_ack`; ack = verified, timeout = failed).

**Scripted part** (own throwaway hub; prints the check envelope, the ack round trip,
the timeout verdict, and the automatic check on attach-during-shift):

```
uv run python scripts/runbook/delivery_check.py
```

**Manual part — real sessions:**

1. With a shift running, open a spare terminal in an agent's workdir and start a bare
   `claude` (no channel flag). Within seconds the board raises "**<agent> cannot hear
   the hub**" with the restart remedy, and the card foot reads *started without the
   channel* in red. (The bare session steals the agent's channel — this is the exact
   item-30/31 situation, now labeled instead of silent.)
2. Close that session, then End shift / Start shift. As each fresh session attaches,
   the hub sends it a delivery check automatically: the card foot shows *checking
   delivery…*, then the small chip on the card turns into a green **✓** as the model
   calls `courtyard_ack` (its terminal shows the tool call). No popup, no red.
3. **On demand:** hover a connected agent's card — the **✓?** chip; click it and watch
   the same pending → ✓ cycle. Hovering the green ✓ shows when delivery was last
   verified.
4. **The failure verdict:** repeat step 1's bare session and click its card's **✓?**.
   After the timeout (60 s) the foot turns to *delivery check failed* (the flag warning
   outranks it when both apply). Expected everywhere: the check never appears in any
   line history or archive.

---

## Envelope visibility on the Admin page (item 29, visibility half)

**Feature under test:** Admin → **Envelope** ("What the agents read"): eight
collapsible blocks, one per delivery case plus the adapter instructions, served by
`GET /api/envelope` from the same `render()` that wraps real deliveries.

1. Open Admin, scroll to Envelope: eight rows, each with a one-line note on when it
   applies. Expand "A question from a peer": the full `<courtyard-message>` sample
   with the agent preamble and the reply footer. Expand "The delivery check": the
   `courtyard_ack` instruction with a placeholder token.
2. Cross-check honesty: send a real agent a message and compare the pane's raw text
   (or the adapter stderr log) with the matching sample; the wrapper must be
   identical apart from names, ids and the body.
3. Zero errors in the browser console.

---

## The pi adapter (design §7.3, D32, item 36)

**Feature under test:** the second adapter — one extension file
(`.pi/extensions/courtyard.ts`) written by install, speaking the same hub contract
as the Claude Code adapter.

**Scripted part** (runs the exact install-written file under Node with a stub `pi`
object against a real hub: attach with `channel_flag: present`, push arrives as a
`customType: "courtyard"` message with `triggerTurn`/`followUp`, reply through the
turn machine, a turn violation surfaced verbatim, the delivery check acked, clean
detach):

```
uv run pytest tests/test_pi_adapter.py -q
```

**Manual part — a real pi session** (needs pi installed: `npm i -g @earendil-works/pi-coding-agent`):

1. Register an agent with `--type pi` and a workdir; install writes the extension,
   the wrapper, and the etiquette skill (`.pi/skills/courtyard/SKILL.md`). Run `./start-with-courtyard.sh` there: the card goes green with
   `channel_flag` present, and — with a shift on — the delivery check turns the ✓
   green as the model calls `courtyard_ack`.
2. Message it from the board: the envelope appears in the pi session as a courtyard
   message (not as user input), and the model's reply comes back via
   `courtyard_send` and lands on the board.
3. In the pi TUI: the footer shows `⏺ <agent> · courtyard · connected`; incoming
   envelopes render as courtyard cards (sender + kind header), not raw XML;
   `/courtyard` answers with the connection and queue without an LLM turn; and
   `.courtyard/adapter.log` in the workdir logs every delivery.
4. Mixed team: one claude-code agent and one pi agent on a line, a relayed question
   through the gate — same turn-taking, same envelope, both directions.

## The team charter registry, read path (design team-charter.md, D33 — slice 1)

**Feature under test:** registering team charter directories with the hub, loading and
displaying what the files say, explicit reload, and current-team selection. A hub with
no team registered behaves exactly as before. Slice 2 (below) adds projection: since
then, selecting or reloading the CURRENT team also changes registrations and lines.

**Scripted part** (its own throwaway hub; add the committed demo charter, initialize a
charter-less dir, edit-then-reload, broken charter renders a report, current selection,
remove leaves the files — plus the slice 2 checkpoints of the next entry):

```
uv run python scripts/runbook/team_charter.py
```

**Manual part** (any hub, the WebUI):

1. Admin → Teams → "add a team" → browse. On macOS the REAL system folder dialog
   opens (browser pickers cannot return absolute paths, so the hub shows its own
   native dialog; the old in-page browse dialog remains as the fallback and can be
   forced with `COURTYARD_NATIVE_PICKER=0` on the hub — the scripted checks do).
   Pick `tests/team-charter` in the repo: the team appears as `demo-devops`,
   "3 agents", no problems; expanding it shows the agent table (infra with
   type/model/colour and all three prose fields) and "loaded at". Cancelling the
   dialog does nothing. The same native dialog now serves the workdir pickers on
   the Agents page.
2. Pick a directory without a `team-definition.yml` instead (empty or not): the panel
   offers to initialize it as a team charter; typing a name and pressing initialize
   creates a commented `team-definition.yml` there, existing files untouched. Cancel
   writes nothing.
3. Edit that file by hand (change the name), reload the Admin page: the hub still shows
   the old name. Press "⟳ reload from disk": the new name appears.
4. Break the file (delete a quote), reload from disk: a readable problem report shows
   in the expanded view; the row survives.
5. Set "Current team" to `demo-devops`: the Courtyard page's Team panel eyebrow reads
   "Team · demo-devops". Set it back to none: plain "Team".
6. Remove a team: a confirm names it, the row goes, the files stay on disk.

## Charter projection: cards become the team (team-charter.md §6, D33 — slice 2)

**Feature under test:** selecting a team as current (or reloading the current team)
projects the charter into the database: cards become registrations, declared links
become lines with their gate modes, the per-machine workdir overlay fills workdirs,
and the anti-scope reaches the peers roster. Additive only: nothing is ever removed
by a reload. Do the manual part on a scratch hub, not the dev hub — selecting a team
registers its agents for good (names are permanent).

**Scripted part** (rides the same script as slice 1: projection on select, the
workdir answer and overlay file, edit-then-reload mirroring, declared-mode reassert,
the shift guard):

```
uv run python scripts/runbook/team_charter.py
```

**Manual part** (a scratch hub, the WebUI):

1. Admin → Teams → add `tests/team-charter` and set it as "Current team": three
   agents appear on the Courtyard page (infra blue, claude-code, model sonnet), and
   the Lines panel shows infra↔tf-dev (auto-pass, as declared) and infra↔scribe
   (the Admin default). Nothing was typed into an agent form. The Discovery dial
   under Settings → Team now reads manual — the charter declares it (the expanded
   team view says "discovery: manual (declared)"), and a hand flip to auto is
   reasserted at the next reload. A charter without the key leaves the dial alone.
2. In the expanded team view, every agent row carries a "directory on this machine"
   cell reading "not set". Press browse on infra and pick a directory: the overlay
   file `workdirs.local.yml` appears in the charter directory (with its never-commit
   header) and infra's registration carries the workdir (Agents page shows it).
3. Edit `infra/description.md` on disk, press "⟳ reload from disk": the new text is
   on infra's card and in the team view. Flip the infra↔tf-dev line to supervised in
   the pane, reload again: it returns to auto-pass (the charter declares that mode);
   a flip on infra↔scribe survives reloads (no declared mode).
4. Register an agent by hand, reload the team: it is untouched — projection adds and
   mirrors, never removes.
5. The anti-scope: on the Agents page, infra's edit view shows the "not for" text
   from `anti-scope.md`; the field is editable on both agent forms (and while the
   team is current, saving the form writes the file too: write-back, next entry).
6. Start a shift, try "⟳ reload from disk" on the current team: refused with "a
   shift is running; end it before reloading the current team". The "Current team"
   pulldown refuses the same way. End the shift: both work again.

## Charter write-back: the agent forms write the files (team-charter.md §3, D33, slice 3)

**Feature under test:** while a team is current, agent registration changes made
through the hub also land on the charter files, so the files stay the master: add
writes the yml entry, the configuration directory with `card.yml` and the prose
files, and the workdir into `workdirs.local.yml`; an edit of a charter agent
rewrites its card files (a cleared field deletes its file); removal takes the yml
entry, the links naming the agent, the overlay entry and the configuration
directory back out. Agents registered without a current team, or before the team
was current, stay database-only. Do the manual part on a scratch hub with a COPY of
`tests/team-charter` (write-back edits the charter directory, and registering
agents burns permanent names).

**Scripted part** (step 9 of the same script):

```
uv run python scripts/runbook/team_charter.py
```

**Manual part** (a scratch hub, the WebUI, a copied charter dir set as current):

1. On the Agents page, open "+ Add an agent": the form carries a note that the new
   agent is also written into the charter directory. Register one with all fields
   filled and a workdir picked: the charter directory gains `<name>/` with
   `card.yml`, `description.md`, `owns.md`, `anti-scope.md`, the yml gains the
   agent entry, and `workdirs.local.yml` gains the workdir. The team view (Admin →
   Teams) already lists the new agent without a reload.
2. Edit that agent: change the model, clear the anti-scope, save. `card.yml` shows
   the new model; `anti-scope.md` is gone; the note above the save button names the
   charter directory.
3. Edit an agent that is NOT in the charter (registered before the team was
   current): no note on the form, and the charter files do not change.
4. Remove the charter agent: the dialog states it leaves the files too. After
   remove, the yml entry, its links and its directory are gone; "⟳ reload from
   disk" reports nothing and does not resurrect it.
5. Break `team-definition.yml` on disk (e.g. `team: [broken`), reload the team,
   then try to add an agent: refused with `charter_not_loaded` and nothing is
   registered. Clear the "Current team" selection: adding works again (database
   only), and the add form now says so - "No team is current: this agent goes
   into the database only", with a link to Admin. Restore the file.

## Log level: one knob, honest severity (COURTYARD_LOG_LEVEL)

**Feature under test:** `COURTYARD_LOG_LEVEL` (in `.env` or the environment; INFO
default, WARNING, ERROR, and DEBUG for development) sets the hub's stdout
verbosity in one place: the hub's own loggers, uvicorn's, and the request lines.
Request lines log at their real severity instead of uvicorn's always-INFO: below
400 INFO, 4xx WARNING, 5xx ERROR. So WARNING keeps failures visible while routine
200 lines go quiet (the startup banner goes quiet too; that is what WARNING
means).

**Scripted part** (its own throwaway hub, runs the hub twice):

```
uv run python scripts/runbook/log_level.py
```

**Manual part:**

1. `COURTYARD_LOG_LEVEL=WARNING make run`: no startup banner, no request lines
   while the WebUI loads. Trigger a refusal (add a team from a directory without
   a charter and cancel the name prompt): the 422 line appears, labeled WARNING.
2. Stop, run plain `make run`: the familiar INFO lines are back, and the same
   422 shows as WARNING among them.

---

## Threads: the quant of conversation (design threads.md, D34 - slice 1)

**Feature under test:** every message belongs to a thread, one bounded exchange
about one ask. Serial v1: at most one open thread per line. The first message on
a quiet line opens one (declared or not); a declared new ask (`new_thread` on the
send) while a thread is open is refused like a turn violation. Close is a
dedicated tool call (`courtyard_close_thread`), initiator-only, with no message
and no note: it resolves the line's reply obligation and the peer gets the fixed
system line "thread closed by X". The answer's envelope points the initiator, and
only the initiator, at the close tool. End shift marks open threads `expired`.
The operator's threads need no declaration and close through
`POST /api/operator/close-thread` (the pane's "close thread" control, slice 3).

**Scripted part** (against a live hub; the expiry checkpoint skips itself unless
every other line is idle and no real claude-code agent is down):

```
make run                        # hub in another terminal
uv run python scripts/runbook/threads.py
```

Checkpoints printed: same thread id on ask and answer; the `thread_open` refusal
text; the close-tool pointer in the rendered answer; the `not_thread_initiator`
refusal; closed state + idle line + the peer's notice; a fresh thread for the
next ask; `expired` state and its system entry after a forced end shift.

**Manual part** (needs a live agent session, e.g. the comms round trip setup):

1. Ask a connected agent something and read its answer in the conversation pane;
   check the hub log or `GET /api/lines/<id>/threads` shows one open thread
   opened by `operator`.
2. Close it: `curl -X POST http://127.0.0.1:2626/api/operator/close-thread -H
   'Content-Type: application/json' -d '{"peer": "<agent>"}'`. The pane gains the
   system line "thread closed by operator", delivered to the agent's session.
3. Have the agent ask YOU something and answer it: the agent's envelope pointed
   it at `courtyard_close_thread`, and a well-behaved session closes its thread
   after your answer settles it - watch for the close in the pane.


---

## Per-thread budgets (design threads.md section 5 item 2, D34 - slice 2)

**Feature under test:** every agent-agent thread carries an exchange budget
(Admin default, `thread_budget`, 12 messages; 0 disables it). A reply always
passes, so a line can never jam on an obligation. The send that would grow a
spent thread with a fresh ask locks the thread (`locked`, kept in history),
writes a durable system line to each participant, and is refused with
`thread_locked`; the next ask opens a fresh thread. Returned and dropped
messages never count. Threads with the operator in them are never locked.

**Scripted part** (its own throwaway hub; flips the courtyard-wide budget):

```
uv run python scripts/runbook/thread_budget.py
```

Checkpoints printed: the default (12) and the dial; the lock with both refusal
texts; `locked` state surviving the refusal; idle line; two system lines, one
per side; fresh thread after the lock; a reply passing past the budget; a
returned message not counting; the operator exempt; 0 = unbudgeted.

**Manual part:**

1. Admin page, Defaults panel: the "Thread budget" input shows 12. Set it to 0
   and back; a negative value is refused by the input itself.
2. On a scratch hub (or accepting locked threads on the dev hub), set the
   budget to 2, let two agents exchange two messages on one ask, then have one
   send a follow-up: the pane shows the two "thread locked" system lines and
   the sender's session shows the refusal text.


---

## Threads in the WebUI: boundaries, counts, the close control (D34 - slice 3)

**Feature under test:** the conversation pane groups messages by thread: a divider
chip at each thread's first message names its number, opener and state (open is
blue, locked amber, closed and expired muted); messages older than the threads
migration stay ungrouped at the top. The wire on the Lines panel counts the asks:
"supervised · 3 threads, 1 open · 2m ago". The pane header of your own line shows
a "close thread" button exactly when the open thread is one you initiated; it
confirms, then invokes the same hub operation as the agents' close tool, and the
divider flips live over SSE.

**Scripted part:** the hub half is `scripts/runbook/threads.py` (see the slice 1
entry); the UI is verified by hand.

**Manual part** (`make demo` or any hub with two agents that have talked):

1. Lines panel: a wire whose pair has exchanged messages reads "N threads" in its
   sub-line, with ", 1 open" while an ask is unsettled.
2. Select that line: divider chips split the scroll by ask, each naming who opened
   the thread and its state; a "thread closed by X" system line sits at each
   healthy ending. No "close thread" button appears here (the initiator closes,
   and that is not you).
3. Message an agent from its card. Your open thread shows a blue "thread N · you ·
   open" chip and the header gains "close thread". Click it, accept the confirm:
   the chip flips to closed without a reload, the button goes away, and the agent
   receives the system line.
4. Have the agent message you first (or use a dummy): the chip reads its name as
   opener and the header shows no close button - that thread is the agent's to
   close.

