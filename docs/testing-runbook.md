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
**remove**. *launch config* opens the `.mcp.json` (or puppet command) with the token and
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
added/validated/removed (item 20), the machine through a full cycle — spawns nothing: the throwaway agent is a puppet, and it refuses to run the shift
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
make demo          # hub + scripted puppets; open http://127.0.0.1:2626/ when it says so
make demo-stop     # afterwards
```

**Expected** (in the browser, the Courtyard page):

1. **Team** — one rectangle per demo puppet, each on its own colour (the hub hands out
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
