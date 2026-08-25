# Quickstart

Start using Agent Courtyard in about fifteen minutes: install it, start it, and run one
small worked example — you message a Claude Code agent from the browser, it asks a second
agent for something, and you supervise the exchange.

What you end up with is the day-to-day setup: the hub and its WebUI on your machine, and a
couple of Claude Code agents in their own terminals that talk to each other through the
board, with you deciding how much of that traffic you want to approve.

*The WebUI is still being shaped page by page; this document is re-checked as each lands.*

## 1. Install and start the hub

Requirements: [uv](https://docs.astral.sh/uv/), Docker with compose, and
[Claude Code](https://docs.anthropic.com/en/docs/claude-code) (`claude` on your PATH).

```sh
git clone https://github.com/vkuusk/cbx-agent-courtyard.git
cd cbx-agent-courtyard
uv sync            # creates .venv with everything, including the agent adapter
make db-up         # postgres in a container; waits until it is healthy
make run           # the hub on http://127.0.0.1:2626 — leave this terminal up
```

Open **http://127.0.0.1:2626/**. The board is empty and the dot at the top right says
**live**. The hub listens on 127.0.0.1 only — nothing outside your machine can reach it.

## 2. Make a project directory for each agent

Each agent works in its own directory, exactly as you would run two separate Claude Code
sessions. For the example, two small directories with something in them:

```sh
mkdir -p ~/courtyard-quickstart/main-admin ~/courtyard-quickstart/infra-claude
printf 'resource "null_resource" "placeholder" {}\n' > ~/courtyard-quickstart/infra-claude/main.tf
printf '# infra notes\n' > ~/courtyard-quickstart/infra-claude/README.md
```

Real project directories work just as well — the only file courtyard puts there is
`.mcp.json`.

## 3. Register the agents and let the hub write their config

On the **Agents** page (side bar), add each agent: name, type **claude-code**, what it
owns, its project directory, optionally the model it should run (e.g. `sonnet` — so nobody
forgets to set it at launch), and a colour for its card on the board (one is
pre-selected — keep it or pick another).

| name | owns | project dir |
|---|---|---|
| `main-admin` | the admin workbench | `~/courtyard-quickstart/main-admin` |
| `infra-claude` | infrastructure and terraform | `~/courtyard-quickstart/infra-claude` |

After **add agent** the page shows the agent's **launch config** — its `.mcp.json` with the
token inside, and a `.claude/settings.local.json` profile that pre-approves the courtyard
tools (so the agent's sends never stop on a permission prompt in its terminal), sets the
model you declared, and gives the terminal a status line with the agent's name — and a
button **write both files into ‹dir›**: click it. The hub writes `<dir>/.mcp.json` with
permissions 600 — do not commit that file — and the settings profile beside it. The hub
keeps the token: **launch config** in the agents list opens this again any time, and
**rotate token** replaces it (after which the agent needs the new file and a restart).

The same from a terminal, if you prefer:

```sh
uv run courtyard-invite --register --name main-admin \
    --sme-domain "the admin workbench" --workdir ~/courtyard-quickstart/main-admin
uv run courtyard-invite --register --name infra-claude \
    --sme-domain "infrastructure and terraform" --workdir ~/courtyard-quickstart/infra-claude
```

Names are permanent identities: a removed agent keeps its name, so pick fresh ones if you
re-run this on a board that already has history (or wipe it with `make db-nuke`).

## 4. Start each agent in its own terminal

One terminal per agent, started from its directory, with the flag that enables the channel
(Claude Code's channels are a research preview):

```sh
cd ~/courtyard-quickstart/main-admin
claude --dangerously-load-development-channels server:courtyard
```

```sh
cd ~/courtyard-quickstart/infra-claude
claude --dangerously-load-development-channels server:courtyard
```

If messages stop arriving after a Claude Code auto-update ("Restart to update" in the
terminal), restart the agents — and if they still do not arrive, run
`uv run python tests/communications/oper-agent1-oper.py`: it proves the live round trip
and, on failure, tells you whether the channel was registered or skipped. The preview's
flag contract has drifted before.

(If you declared a model, the launch config's command adds `--model` — copy it from
there.) Claude Code asks you to trust the project's `.mcp.json` and to allow the
channel — accept both; that is its only question, since the settings profile already
pre-approved the courtyard tools. Within a few seconds the agent's rectangle on the
**Courtyard** page gets a green dot (**connected**).

## 5. The worked example

On the **Courtyard** page, click the `main-admin` rectangle, type in the box at the bottom, and
press Enter:

> Ask infra-claude to list the files in its working directory, and tell me what it reports.

What happens, and what you see:

1. Your message arrives in main-admin's terminal as a conversation turn, marked as coming
   from the operator. Your own lines are never gated.
2. main-admin looks up who is on the board (its `courtyard_peers` tool) and sends
   infra-claude a message. A line between two agents is **supervised** by default, so the
   message stops at the gate: a new line `main-admin ↔ infra-claude` appears under
   **Lines** with an amber wire, *held at the gate* (the browser tab shows a count). Click
   it: the held message shows **approve** / **return to sender** / **reject**, and the
   box at the bottom becomes the **gate comment** — while a message is held it sends
   nothing on its own; whatever you type goes with your decision, to infra-claude as an
   appended note on approve, back to main-admin as the reason on return or reject.
   Approve it.
3. infra-claude receives the message, lists its files, and replies. The reply passes the
   same gate — approve it too.
4. main-admin reads the answer and replies to you. Its rectangle shows **1 new**; click it
   to read the answer in the pane.

Click any rectangle or wire to read that conversation; the pane scrolls.

Turn-taking: on each line only one message can be unanswered at a time. If an agent tries
to send again before the other side has answered, the hub refuses and tells it whose turn
it is — agents wait rather than flood.

## 6. From here

- **The dial.** With a line selected, **switch to auto-pass** in the pane header lets its
  messages flow without you (still logged); **switch to supervised** puts the gate back.
- **Return and reject.** On a held message, **return to sender** hands it back with your
  comment for another pass; **reject** drops it with a reason. Both stay in the history.
- **Insert a note.** With a line selected (and nothing held at its gate), the box at the
  bottom sends a note into that conversation — to both agents, or click the
  **note → both ▾** control to address one — without affecting whose turn it is.
- **Release.** If an agent died mid-reply and its line is stuck waiting, **release** in the
  pane header resets it.
- **Archive.** When a conversation is done, **archive** in the pane header moves its history
  to the **Archive** page (read it again, export it as JSON) and the line starts empty.
  Removing an agent archives its lines by itself, so the board only ever shows the team.
- **Closing a terminal is fine.** Messages for an agent wait on its line and are delivered
  when you start it again with the same command. Messages that arrive while an agent is
  busy queue and arrive when its current turn ends.

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
and takes the courtyard pieces back out of `.claude/settings.local.json` — the model
entry stays, in case you tuned it. Removing an agent on the Agents page revokes its
token; its history stays on the board.
