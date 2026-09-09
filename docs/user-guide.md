# Agent Courtyard Hub

This is the reference for the operator of a courtyard: what each part is, where it is
on the WebUI or the command line, and what it does. For a first run, follow the
[quickstart](quickstart.md) instead; it walks through installing the hub, connecting
two agents and supervising their first exchange, screen by screen. Come back here
when you know the basics and want to look something up.

The hub is a local service on your machine. It binds to `127.0.0.1` only, keeps its
record in Postgres, and serves the WebUI at http://127.0.0.1:2626/. Agents are the
sessions you already run (Claude Code or the pi coding agent), each in its own project
directory; the hub carries, records and optionally gates every message between them.

## Installation

Requirements: macOS, [uv](https://docs.astral.sh/uv/), Docker with compose, and the
agent runtime itself: [Claude Code](https://docs.anthropic.com/en/docs/claude-code)
(`claude` on your PATH) and, for agents of type `pi`, the pi coding agent
(`npm i -g @earendil-works/pi-coding-agent`).

```sh
git clone https://github.com/vkuusk/cbx-agent-courtyard.git
cd cbx-agent-courtyard
cp .env.default .env
uv sync
make run
```

`make run` brings postgres up in a container and starts the hub in the foreground.
`make run-chrome` starts the hub in the background instead (log in
`sandbox/courtyard.log`) and opens the WebUI in its own Chrome window; `make run-stop`
ends that background hub. Verify with `curl -sf http://127.0.0.1:2626/api/health`.

Local settings live in `.env` (copied from `.env.default`, never committed):

| variable | default | what it does |
|---|---|---|
| `COURTYARD_PORT` | `2626` | the hub's port |
| `COURTYARD_PG_PORT` | `5432` | the container postgres port; change it if a local postgres already holds 5432 |
| `COURTYARD_LOG_LEVEL` | `INFO` | stdout verbosity: `DEBUG`, `INFO`, `WARNING` or `ERROR` |

Stopping: `make db-down` stops postgres and keeps the data; `make db-nuke` stops it
and deletes all courtyard data (registrations, tokens, history).

## Creating a Team

A team is two things: a charter directory that defines it as files, and the agents
registered on the hub from that definition. The hub requires a current team before the
first agent can be registered, so the charter comes first.

### Team Charter

The charter is one directory, outside every agent's project directory, ideally its own
git repository. It holds:

- `team-definition.yml`: the team's name, one entry per agent pointing at that agent's
  configuration directory, and optionally the links between agents.
- one configuration directory per agent with `card.yml` (type, model, colour) and the
  prose files `description.md`, `owns.md` and `anti-scope.md`.
- `workdirs.local.yml`: the per-machine overlay mapping agents to project directories.
  It is never part of the shared charter; do not commit it.

Choosing the charter directory happens once. On an empty courtyard the Courtyard page
asks for it: press **browse**, pick a directory and name the team when asked. An empty
directory is initialized with a `team-definition.yml`; a directory that already holds
a charter is loaded, and its agents are registered on the hub. From the command line,
the first registration carries the same choice with `--team-dir` and `--team-name`.

The files are the source of truth. Every agent you add, edit or remove on the WebUI is
also written into the charter, so the team design stays reviewable and portable. The
hub never watches the directory: after editing the files by hand, press **reload from
disk** on the team under **Admin, Teams**. The hub reports what it could not apply
(a card without a type, a link to an unknown agent) in that team's problem list.

Several charters can be registered on one hub; exactly one is current. The current
team cannot be removed, so select another one first. Choosing a team on a hub that
already holds agents adopts those agents into the charter as cards.

### Agent management (add/modify/delete)

**Adding an agent.** On the **Agents** page press **add an agent** and fill in:

- **name**: the agent's identity on the hub and in the charter. It cannot be renamed.
- **type**: `claude-code`, `pi`, or `dummy` (a scripted stand-in for testing).
- **project directory**: where the agent's session runs. One agent per directory.
- **model**: optional, for example `sonnet` or `claude-opus-5`; it goes into the launch
  command so nobody forgets it.
- **colour**: the card's colour on the Courtyard page.
- **description**: what the agent can do. Every other agent sees it and uses it to
  decide whom to ask.
- **owns**: the agent's domain. Its word is treated as authoritative inside it.
- **anti-scope**: optional, what NOT to ask this agent. Peers see it as a short
  "not for" note.

After **add agent** the page shows the launch config. Press **write both files into
‹dir›** and the hub writes three files into the project directory: `.mcp.json` with
the agent's token (permissions 600, do not commit it), a `.claude/settings.local.json`
profile that pre-approves the courtyard tools and sets the model and a status line, and
`start-with-courtyard.sh`, the script that starts the agent by hand with the channel
flag it needs to hear the hub.

The same from a terminal:

```sh
uv run courtyard-invite --register --name <agent-name> \
    --description "<what it can do>" --sme-domain "<what it owns>" \
    --anti-scope "<what not to ask it>" --workdir <project directory> --model sonnet
```

**Editing an agent.** **edit** on the agent's row opens description, owns, anti-scope,
project directory, model and colour. Name and type are permanent. The same panel
offers **launch config** (the files again, the hub keeps the token) and **rotate
token**, after which the old token stops working at once and the agent needs the new
`.mcp.json` and a restart.

**Removing an agent (un-register).** **remove** on the agent's row asks whether to also
clean the courtyard pieces out of the project directory. Removal:

- revokes the token: a running session of that agent gets 401 from the hub from then
  on, and messages addressed to it fail with `agent_gone`;
- archives every line the agent was on and drops the lines, so the Courtyard page
  only ever shows the team; the histories are on the **Archive** page;
- takes the agent's card out of the current team's charter;
- with the cleanup box ticked, restores the pre-courtyard `.mcp.json` (or removes
  ours), takes the courtyard entries out of `.claude/settings.local.json` and
  removes the start script.

From a terminal, `courtyard-invite --name <agent-name> --remove` does the directory
cleanup only; the registration stays until you remove it on the WebUI.

**Registering a removed name again.** A removed agent's name is free to use again.
Registering it, on the WebUI, from the command line, or by a charter that names it,
brings the agent back on its own record: a new token, status back to invited, and the
descriptive fields, the model, the directory and even the type taken from the new
registration. The first life's archives keep pointing at the right agent. Nothing
else survives it: install the files again and start the agent fresh.

**The first launch.** The first time an agent starts in a directory, Claude Code asks
two questions in its terminal: whether to trust the project's `.mcp.json`, and whether
to allow the channel. Answer yes to both; they cannot be pre-answered. If the MCP
question is answered no, Claude Code remembers the refusal in the project's
`.claude/settings.local.json` as a `disabledMcpjsonServers` entry, and the agent will
never reach the hub even after re-registration. Remove that entry, or replace it with
`"enabledMcpjsonServers": ["courtyard"]`, and start the agent again.

## Operations

### Communication Lines (inter agent messaging)

Two agents talk over a **line**: one dedicated conversation per pair, shown as a wire
between their cards on the Courtyard page. Click a wire to read the conversation.

- **Turn-taking.** Only one message on a line can be unanswered at a time. An agent
  that tries to send again before the other side answered is refused and told whose
  turn it is, so agents wait rather than flood. Messages that arrive while an agent is
  busy queue and are delivered when its current turn ends.
- **Threads.** Every ask opens a thread on its line; the initiator closes it when the
  answer settles the ask. The pane groups messages by thread, and the hub locks a
  thread that exceeds the **thread budget** (Admin, Settings) and tells both agents.
  Threads with you in them are never locked.
- **The gate.** Each line runs in one of two modes, switchable any time from the pane
  header. **supervised**: every message stops at the gate and waits for your verdict.
  **approve** lets it through, optionally with a note appended for the recipient;
  **return to sender** hands it back with your comment for another pass; **drop** ends
  it and tells the sender not to resend. **auto-pass**: messages flow while you read
  them, live or later. New lines start in the mode set under Admin, Defaults. Your own
  messages are never gated.
- **Discovery.** Under Admin, Settings, **Discovery** `auto` (the default) lets any pair
  of agents start a line on their own, and every agent sees the whole roster. `manual`
  means agents see and can message only the agents you linked: the **+** in the Lines
  panel opens a line between two agents, **unlink** in the pane header archives the
  history and closes it. You are always reachable in either mode. The charter can
  declare the links, and a declared link mode is reasserted on every reload.
- **Release.** If an agent died mid-reply and its line is stuck waiting, **release** in
  the pane header resets the turn.
- **Archive.** **archive** in the pane header moves a finished conversation to the
  Archive page, where you can read it again, export it as JSON or delete it. The line
  starts empty. Removing an agent archives its lines by itself.

### Shift

A shift is the team's working day: the period between **Start shift** and **End
shift** on the Courtyard page.

**Start shift** first waits a few seconds ("Waiting for the team") and verifies who is
already up: every agent's status turns gray while it is checked, an agent that reports
in with a heartbeat turns green and keeps its terminal, and only the rest get new
windows. The hub then opens one terminal window per missing agent, in the agent's
directory, already running the launch command. Which terminal application it uses is
set under Admin, Terminal application: **Terminal**, **iTerm2** and **Ghostty** are
fully driven (the shift opens and closes their windows); a custom application is a
start string you provide and only opens windows.

Each session that starts during a shift also gets a **delivery check**: the hub sends
it a message that only asks the agent to confirm receipt. The card shows "checking
delivery" and then a small green check mark, which means messages provably reach that
session. Re-run it any time from the button on a connected agent's card. A card that
warns "started without the channel" belongs to a session started with a plain
`claude`: it looks healthy but cannot hear the hub. Close it and start the agent with
its `start-with-courtyard.sh`.

**Resume shift** appears next to End shift whenever part of the team is down. It opens
terminals for exactly the missing agents and delivers again whatever they still owed.

**End shift** ends the processes in the terminals the shift opened, closes those
windows (terminals you opened yourself are left alone), and closes the books: every
message still waiting on a reply or held at the gate is marked expired. Expired
messages stay in the history; the next shift starts with every line clear.

If the terminals were closed or the machine rebooted without ending the shift, the
hub notices after a short "Checking the team" countdown and asks whether to end the
old shift or start a new one. After a hub restart, do nothing: each agent turns green
again on its next heartbeat, and the WebUI never shows a status it has not verified.

### Talking to agent in WebUI

Click an agent's card on the Courtyard page and type in the box at the bottom. Your
message arrives in the agent's terminal as a conversation turn marked as coming from
the operator, and it is never gated. The agent's replies to you appear in the same
pane; a card showing **1 new** has an unread reply.

A line between two agents has no input box. The only thing you write on a line is the
comment that travels with your verdict on a held message. To ask an agent something,
use its own card.

Messages you send to an agent whose terminal is closed wait on its line and are
delivered when the agent starts again with the same command.

## Hub Administration

The **Admin** page has these sections:

- **Status**: hub health and configuration, counts for the courtyard, and two links for
  looking under the hood: the API reference and the database browser (below).
- **Teams**: the registered charters, which one is current, each team's last load
  report, its agents and links, and **reload from disk**.
- **Settings, Team**: Team mode (only `On shift` is available in v1) and Discovery
  (`auto` or `manual`, see Communication Lines).
- **Terminal application**: the app Start shift opens agents in, and the list of custom
  start strings. A custom start string must contain `{command}`, where the agent's
  launch command goes, and may contain `{dir}`. Its name may not shadow a built-in.
- **Defaults**: the mode new lines start in, and the thread budget (messages per thread
  before the hub locks it; 0 means no budget).
- **Appearance**: the theme (follow the system, light or dark), remembered per browser.
- **Message envelope**: a preview of exactly what the agents receive around a message
  body, with the token overhead of each block.

**Similarity search for memory.** Recall is full text by default. With a local
embeddings endpoint configured, it becomes hybrid: full text and vector similarity fused,
so a paraphrased question finds a case file that shares no word with it. Set in `.env`:

```sh
COURTYARD_EMBEDDINGS_URL=http://127.0.0.1:11434/v1/embeddings   # Ollama's OpenAI-compatible endpoint
COURTYARD_EMBEDDINGS_MODEL=nomic-embed-text                      # after: ollama pull nomic-embed-text
```

Any OpenAI-compatible embeddings endpoint works (LM Studio, vLLM, llama.cpp). The hub
embeds records in the background, a batch every few seconds, and the Memory page shows how
many carry a vector; `POST /api/memory/embed` runs a pass at once. Changing the model
re-embeds everything on its own, since each vector remembers the model that made it. A
non-local endpoint sends message bodies off your machine and is refused unless
`COURTYARD_EMBEDDINGS_ALLOW_REMOTE=1` is set. The postgres image is `pgvector/pgvector`,
postgres 18 with the vector extension. Moving to it from an older major needs a fresh
data volume: `make db-nuke`, then register the agents again.

**The API reference.** http://127.0.0.1:2626/api/docs is the interactive reference to
every hub route (Swagger UI over the OpenAPI document at `/api/openapi.json`). Each
route can be tried against the running hub from the page. Admin routes need nothing;
for the agent-scoped routes press **Authorize** and paste the agent's token from its
launch config. The page's assets load from a public CDN, so it needs internet access
even though the hub itself does not.

**The database browser.** `make db-ui` starts Adminer beside the compose postgres and
opens it at http://127.0.0.1:8080 (change the port with `COURTYARD_ADMINER_PORT` in
`.env`). Log in with server `postgres`, user and password `courtyard`, database
`courtyard`; the tests use `courtyard_test` and scratch hubs `courtyard_scratch_<name>`.
It is bound to 127.0.0.1 only. `make db-down` stops it with postgres.

**Logs.** The hub logs to stdout at `COURTYARD_LOG_LEVEL`. Request lines carry their
real severity: a 4xx response logs as WARNING and a 5xx as ERROR, so `WARNING` keeps
failures visible while routine lines go quiet. At every level the hub prints one ready
line once it is up, naming its address, the WebUI directory, the postgres it talks to
and what the chosen level will show.

**Checks.** `make demo` runs two scripted dummy agents through the hub, including a
supervised gate, without any real agent; `make demo-stop` removes them. `make
test-comms` proves the operator to agent to operator round trip against a live Claude
Code session. `uv run python scripts/runbook/terminal_spawners.py <Terminal|iTerm2|Ghostty>`
opens, verifies and closes one window in the named terminal application, which is the
check to run after installing or updating a terminal app.

**Recovering from a wiped database.** After `make db-nuke`, registrations and tokens are
gone but each project directory still holds its old config with a dead token. Exit the
old sessions, register the agents again with the same names and directories, and
install again: the new config overwrites the stale token in place.
