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
(then `make db-up && make run` again) clears registrations left by earlier runs.

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
   exchange is complete and no reply is owed". Notes and system messages have no footer.
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

**Scripted part** (settings round trip, `always_on` refused, the machine through a full
cycle — spawns nothing: the throwaway agent is a puppet, and it refuses to run the shift
if real claude-code agents are down):

```
make db-up && make run          # hub in another terminal
uv run python scripts/runbook/shift_and_settings.py
```

**Manual part — the real spawn** (his live check; opens actual windows):

1. With the hub freshly restarted and one claude-code agent's terminal closed, press
   **▶ Start shift** on the Courtyard page. Expect the amber countdown
   (`Waiting for the team · N`, ticking) — then exactly one terminal window opens
   (Admin → Team chooses Terminal or iTerm2), already in the agent's workdir with the
   launch command running; the pill shows `Starting · x/y` and flips to `● y/y on shift`
   as cards go green. Agents already connected get **no** window.
2. Press **■ End shift** (the square button beside the status pill) → "End the shift?"
   confirm → **every** window the shift opened closes, even when its agent was
   mid-conversation moments before (the hub waits for each window's processes to end
   before closing, escalating TERM → KILL); terminals you opened by hand stay. With a
   line mid-conversation, expect the second confirm ("N lines are mid-conversation…")
   before anything closes.
3. Repeat step 1 when the hub has been up for a while: no countdown — spawning is
   instant.
4. Admin → Team: `Always on` is visibly disabled; switching the terminal app persists
   across a hub restart.

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
make db-up && make run          # hub in another terminal
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
   dimmed, the pill counting `Checking the team · 15` — with **no** green dots and
   **no** question; then, in one transition, the statuses turn offline and the question
   appears — "The last shift was never ended". **■ End shift** is the focused button;
   "Not now" (or Esc / a click outside) leaves the amber *shift left open* tag, which
   reopens the question on click.
2. **Resume shift** → one terminal opens per agent (only the dead ones — a window you
   left open is not doubled), the shift keeps its original start time, and anything an
   agent still owed arrives in its fresh session ("…redelivered" in the line history).
3. Repeat step 1, then **Start new shift** → the old shift's unfinished messages show
   `· expired`, and a brand-new shift starts (fresh terminals, new start time).
4. Restart the hub mid-shift with the agents *running*: the question must NOT appear —
   the cards show "checking…" for at most one heartbeat and turn green as the beats
   arrive, each the moment its agent proves itself (never a false green first).

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
3. **Gate from the pane** (WP-B) — click the amber wire: the pane shows `dev ↔ ops` with
   the **supervised | auto-pass** switch (supervised filled amber; clicking auto-pass
   flips the line and fills green) and the held message with
   **approve / return to sender / reject** — the strip under the buttons names both
   directions (`approve → ops · return / reject → dev`). The box below shows an amber
   **gate comment** chip; its ↑ button is greyed out and Enter sends nothing — the text
   leaves only with a verdict. Type a comment, click **approve**: the box empties, your
   comment appears in the pane as a note `you → ops`, ops's scripted reply arrives *held
   at the gate* (supervised replies pass the gate too). Click **return to sender** with a
   comment: the message is struck through with `returned to sender: <comment>` and the
   hub's notice to dev follows. With nothing held, the box is a note into the line and
   its chip is a visibly clickable **note → both ▾** control (click cycles both → one
   side → the other).
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
