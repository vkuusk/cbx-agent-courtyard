# Quickstart

This is the full walkthrough for a new operator: install the hub, start it, connect
two real Claude Code agents, and supervise their first exchange, with every screen
described. What you end up with is the day-to-day setup: the hub and its WebUI on
your machine, and a couple of Claude Code agents in their own terminals that talk to
each other through the hub, with you deciding how much of that traffic you want to
approve.

## 1. Install and start the hub

Requirements: [uv](https://docs.astral.sh/uv/), Docker with compose, and
[Claude Code](https://docs.anthropic.com/en/docs/claude-code) (`claude` on your PATH).

```sh
git clone https://github.com/vkuusk/cbx-agent-courtyard.git
cd cbx-agent-courtyard
uv sync            # creates .venv with everything, including the agent adapter
make run           # postgres up + the hub on http://127.0.0.1:2626 (leave this terminal up)
```

Open **http://127.0.0.1:2626/**. The Courtyard page is empty and the dot at the top
right says **live**. The hub listens on 127.0.0.1 only, so nothing outside your
machine can reach it.

Alternatively, `make run-chrome` does all of the above in one go: postgres, the hub
in the background (log: `sandbox/courtyard.log`), and the WebUI in its own Chrome
window. `make run-stop` ends the background hub.

## 2. Make a project directory for each agent

Each agent works in its own directory, exactly as you would run two separate Claude Code
sessions. For the example, two small directories with something in them:

```sh
mkdir -p ~/courtyard-quickstart/main-admin ~/courtyard-quickstart/infra-claude
printf 'resource "null_resource" "placeholder" {}\n' > ~/courtyard-quickstart/infra-claude/main.tf
printf '# infra notes\n' > ~/courtyard-quickstart/infra-claude/README.md
```

Real project directories work just as well; the only files courtyard puts there are
the two config files written in the next step.

## 3. Register the agents and let the hub write their config

On the **Agents** page (side bar), add each agent: name, type **claude-code**, a
description of what it can do, what it owns, its project directory, optionally the
model it should run (e.g. `sonnet`, so nobody forgets to set it at launch), and a
colour for its card (one is pre-selected; keep it or pick another).

Take a moment over the two descriptive fields; this is team design, not bookkeeping.
What the agent can do is advertised to every other agent and is how they decide whom
to ask; what it owns marks the agent's word as authoritative inside its own area.

| name | owns | project dir |
|---|---|---|
| `main-admin` | the admin workbench | `~/courtyard-quickstart/main-admin` |
| `infra-claude` | infrastructure and terraform | `~/courtyard-quickstart/infra-claude` |

After **add agent** the page shows the agent's **launch config**: its `.mcp.json` with
the token inside, and a `.claude/settings.local.json` profile that pre-approves the
courtyard tools (so the agent's sends never stop on a permission prompt in its
terminal), sets the model you declared, and gives the terminal a status line with the
agent's name. Click the button **write both files into ‹dir›**. The hub writes
`<dir>/.mcp.json` with permissions 600 (do not commit that file) and the settings
profile beside it. The hub keeps the token.

Nothing is set in stone but the name and type: **edit** on an agent's row opens
everything about it (the descriptions, directory, model and colour, editable any
time), plus **launch config** (this panel again) and **rotate token** (after which
the agent needs the new file and a restart). **remove** asks whether to also clean
the courtyard pieces back out of the agent's project directory.

The same from a terminal, if you prefer:

```sh
uv run courtyard-invite --register --name main-admin \
    --sme-domain "the admin workbench" --workdir ~/courtyard-quickstart/main-admin
uv run courtyard-invite --register --name infra-claude \
    --sme-domain "infrastructure and terraform" --workdir ~/courtyard-quickstart/infra-claude
```

Names are permanent identities: a removed agent keeps its name, so pick fresh ones if
you re-run this on a hub that already has history (or wipe it with `make db-nuke`).

## 4. Start the team: press Start shift

On the **Courtyard** page, press **▶ Start shift** (top right of the Team panel). The
courtyard opens one terminal window per agent, each already in the agent's directory
and already running the launch command, and the pill counts the team up
(`Starting · 1/2` → `● 2/2 on shift`). Right after a hub start it first counts down a
few seconds ("Waiting for the team") to spot agents that are already running before
opening anything. Which terminal app it uses (Terminal or iTerm2) is set under
**Admin → Team**.

The first time an agent starts, answer Claude Code's two questions in its terminal
(trust the project's `.mcp.json`, allow the channel). Accept both; they cannot be
pre-answered, and they are its only questions since the settings profile already
pre-approved the courtyard tools. Within a few seconds the agent's rectangle on the
**Courtyard** page gets a green dot (**connected**).

When the day is done, press **■ End shift** (the square button beside the status
pill). It closes exactly the terminals it opened (terminals you opened yourself are
left alone) and closes the books: any conversation still waiting on a reply, or a
message still held at the gate, is marked **expired**. Expired messages stay in the
history, but the next shift starts with every line clear. If something still matters
tomorrow, just send it again.

You can always start an agent by hand instead: one terminal, its directory, the flag
that enables the channel (Claude Code's channels are a research preview):

```sh
cd ~/courtyard-quickstart/main-admin
claude --dangerously-load-development-channels server:courtyard
```

```sh
cd ~/courtyard-quickstart/infra-claude
claude --dangerously-load-development-channels server:courtyard
```

If messages stop arriving after a Claude Code auto-update ("Restart to update" in the
terminal), restart the agents. If they still do not arrive, run
`uv run python tests/communications/oper-agent1-oper.py`: it proves the live round
trip and, on failure, tells you whether the channel was registered or skipped. The
preview's flag contract has drifted before.

(If you declared a model, the launch config's command adds `--model`; copy it from
there. The shift's spawned terminals include it automatically.)

## 5. The worked example

On the **Courtyard** page, click the `main-admin` rectangle, type in the box at the
bottom, and press Enter:

> Ask infra-claude to list the files in its working directory, and tell me what it reports.

What happens, and what you see:

1. Your message arrives in main-admin's terminal as a conversation turn, marked as coming
   from the operator. Your own lines are never gated.
2. main-admin looks up who is on the team (its `courtyard_peers` tool) and sends
   infra-claude a message. A line between two agents is **supervised** by default, so the
   message stops at the gate: a new line `main-admin ↔ infra-claude` appears under
   **Lines** with an amber wire, *held at the gate* (the browser tab shows a count). Click
   it: the held message shows a plain comment field right under it, then
   **approve** / **return to sender** / **drop**. Whatever you type there goes with your
   decision: to infra-claude as an appended note on approve, back to main-admin as the
   reason on return. On drop it goes nowhere (the message is simply dropped). Approve it.
3. infra-claude receives the message, lists its files, and replies. The reply passes the
   same gate, so approve it too.
4. main-admin reads the answer and replies to you. Its rectangle shows **1 new**; click it
   to read the answer in the pane.

Click any rectangle or wire to read that conversation; the pane scrolls.

Turn-taking: on each line only one message can be unanswered at a time. If an agent tries
to send again before the other side has answered, the hub refuses and tells it whose turn
it is, so agents wait rather than flood.

## 6. From here

- **The dial.** With a line selected, **switch to auto-pass** in the pane header lets its
  messages flow without you (still logged); **switch to supervised** puts the gate back.
- **Return and drop.** On a held message, **return to sender** hands it back with your
  comment for another pass; **drop** ends it: the sender is told not to resend, and your
  comment stays on the WebUI as your own record. Both stay in the history.
- **Questions go to direct chats.** A line between two agents has no input box; the only
  thing you write on a line is the verdict's comment. To ask an agent something, click
  its rectangle and use the box at the bottom.
- **Wire the team yourself.** Admin → Settings → **Discovery** `manual` means agents see
  and can message only whom you have linked. The small **+** in the Lines panel's corner
  opens a line between two agents; **unlink** in its header archives the history and
  closes it. `auto` (the default) lets any pair start talking on their own. You are
  always reachable either way.
- **Release.** If an agent died mid-reply and its line is stuck waiting, **release** in the
  pane header resets it.
- **Archive.** When a conversation is done, **archive** in the pane header moves its history
  to the **Archive** page (read it again, export it as JSON) and the line starts empty.
  Removing an agent archives its lines by itself, so the WebUI only ever shows the team.
- **Closing a terminal is fine.** Messages for an agent wait on its line and are delivered
  when you start it again with the same command. Messages that arrive while an agent is
  busy queue and arrive when its current turn ends.

## When things get out of step

The courtyard keeps its record (in Postgres) even when the pieces around it come and
go: terminals, Claude Code sessions, the hub process. When the record and reality
disagree, these are the moves; each one is safe to do at any time.

- **You closed the terminals (or rebooted) without ending the shift.** After a short
  `Checking the team` countdown (making sure nobody is actually up), the courtyard
  asks "**The last shift was never ended**" and offers two answers. **End shift**
  closes it and nothing more (unfinished messages expire, kept in history), which is
  the answer when you only want to do admin work. **Start new shift** closes the old
  one and starts fresh in one go. "Not now" leaves an amber *shift left open* tag in
  the Team header; click it to get the question back.
- **Part of the team died mid-shift** (a closed or crashed terminal, `1/2 on shift`).
  Press **▶ Resume shift**, which appears next to `■ End shift` whenever someone is
  down. It opens terminals for exactly the missing agents (the healthy ones are never
  touched), and anything the returning agents still owed is delivered again.
- **The hub was restarted mid-shift.** Do nothing. For the first seconds the WebUI
  says so honestly ("checking…" dots, a `Checking the team · 15` countdown), and each
  agent turns green the moment its next heartbeat arrives (within 15 s); the
  terminals own the sessions, not the hub. The WebUI never shows a status it has not
  verified.
- **Claude Code auto-updated under running sessions** (an update banner in the
  terminals, or messages stop getting through). End the shift and start it again;
  fresh sessions run the new version. If messages still misbehave, run
  `make test-comms`: it proves the whole operator → agent → operator path against a
  live session and prints where it broke. Channels are a research preview; the
  launch-flag contract has drifted before.
- **You nuked the database** (`make db-nuke`). Registrations and tokens are gone, but
  each agent directory still holds its old config with a now-dead token; old sessions
  will retry against the new hub forever (harmless 401 noise). Exit those sessions,
  re-register the agents (same names and directories), and **install** again: the new
  config overwrites the stale token in place.

## Stop and clean up

```sh
make db-down       # stop postgres; the data survives
make db-nuke       # stop AND delete all courtyard data
```

To take courtyard back out of a project directory:

```sh
uv run courtyard-invite --name main-admin --workdir ~/courtyard-quickstart/main-admin --remove
```

That restores the `.mcp.json` that was there before (or removes ours if we created it),
and takes the courtyard pieces back out of `.claude/settings.local.json` (the model
entry stays, in case you tuned it). Removing an agent on the Agents page revokes its
token; its history stays on the WebUI.