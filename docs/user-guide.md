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

The short way, for using the hub day to day (details under "Installing as an app" below):

```sh
mkdir -p ~/Applications/courtyard && cd ~/Applications/courtyard
curl -fsSL https://raw.githubusercontent.com/vkuusk/cbx-agent-courtyard/main/install.sh | sh
```

The script checks the prerequisites (macOS, Docker running, Python 3.14) and names what
is missing with the command that installs it; it installs nothing itself. Then it
downloads the newest release zip, unpacks it into the current directory, which must be
empty, and runs `make install`. If you would rather look first: download `install.sh`,
read it, run it. Or skip the script: download the release zip from GitHub, unzip it,
`cd` in, `make install`. The three are the same install.

Settings can ride on the command: the install writes them into the `.env` it creates
(an existing `.env` is kept, and the Summary then warns that they were not applied).
A second instance needs all three of its own: the compose project, the postgres port
and the hub port. With only the project set, two postgres containers fight for one host
port and a hub can end up serving the other instance's database; the hub notices that
(its health reads `error: the database ... is not the one this hub started with` and
every request answers 503 until it is restarted), but the fix is the `.env`. A second,
isolated instance beside the machine's usual one is therefore one line:

```sh
curl -fsSL https://raw.githubusercontent.com/vkuusk/cbx-agent-courtyard/main/install.sh \
    | COURTYARD_COMPOSE_PROJECT=courtyard-2 COURTYARD_PG_PORT=26433 COURTYARD_PORT=2627 sh
```

The other way to give settings ahead of the install is a `.env` written into the
otherwise empty directory first: the script accepts that directory and the install
keeps the file. The same works for `make install` in an unpacked zip or a clone. Accepted on the command:
the three above, `COURTYARD_ADMINER_PORT`, `COURTYARD_LOG_LEVEL` and the
`COURTYARD_EMBEDDINGS_*` settings (the table under Development setup).

The long way, for working on the code:

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
| `COURTYARD_PG_PORT` | `26432` | the compose postgres's host port, deliberately not 5432 so it never collides with a postgres of your own |
| `COURTYARD_COMPOSE_PROJECT` | `courtyard` | the compose project (volume and container names); set it, with the two ports, for a second isolated instance |
| `COURTYARD_LOG_LEVEL` | `INFO` | stdout verbosity: `DEBUG`, `INFO`, `WARNING` or `ERROR` |
| `COURTYARD_ADMINER_PORT` | `8080` | the port `make db-ui` serves the database browser on |
| `COURTYARD_EMBEDDINGS_URL` | unset | an OpenAI-compatible embeddings endpoint on this machine; set, recall becomes hybrid (see Similarity search under Hub Administration) |
| `COURTYARD_EMBEDDINGS_MODEL` | `nomic-embed-text` | the model that endpoint serves |
| `COURTYARD_EMBEDDINGS_API_KEY` | unset | sent as a bearer token if the endpoint wants one |
| `COURTYARD_EMBEDDINGS_ALLOW_REMOTE` | unset | `1` allows an endpoint off this machine (message bodies leave the machine) |
| `COURTYARD_EMBED_SWEEP_SECONDS` | `15` | how often the hub embeds records that lack a vector |

Stopping: `make db-down` stops postgres and keeps the data; `make db-nuke` stops it
and deletes all courtyard data (registrations, tokens, history).

One machine, one courtyard database, by design: every checkout and install shares the
compose project `courtyard`, its volume and its postgres, so a reinstall or a second
directory finds the same team and history. `make install` says which it found ("fresh
courtyard database" or "EXISTING courtyard database found and used: 3 agents, ...") and
how to start from nothing instead. The hub also protects everyone else's postgres: on a
database it has never migrated, tables that are not its own make it refuse to start
rather than create its schema there.

### Installing as an app

For day-to-day use the hub should be out of the way: started at login, restarted if it
dies, opened from the Dock when something needs you. That is `make install`:

```sh
unzip courtyard-<version>.zip && cd courtyard-<version>   # or the git clone
make install
```

Prerequisites: macOS, Docker (Desktop or Colima) set to start at login, Python 3.14
(`brew install python@3.14`); `uv` is used when present and not required. The install
creates `.venv` and `.env`, pulls the postgres image, and writes three things outside the
directory: `~/Library/LaunchAgents/com.courtyard.hub.plist`, a LaunchAgent that runs the
hub at login and restarts it if it exits, `com.courtyard.tray.plist` for the menu bar app
described below, and `~/Applications/Courtyard Admin.app`, the launcher that brings the
menu bar app back after you quit it. The logs are `sandbox/hub.log` and `sandbox/tray.log`.

Install ends by opening the WebUI, which asks whether to keep the courtyard in your Dock.
One click is yours, because browsers only install a site as an app from a click inside
the page: in Chrome the banner's **Add to Dock** button opens the install dialog; in
Safari the banner points at File, Add to Dock. "Not now" hides the question in that
browser, also across later installs; clear the browser's data for 127.0.0.1:2626 to
see it again. When the Dock app already exists from an earlier install, the install opens
it instead of a browser tab. The Dock icon opens the board in its own window and shows
how many messages wait at the gate or are unread for you.

The install closes with a summary: one line per step, OK or WARNING, with every warning
repeated in full so it is not lost above the package output. The two warnings it knows:
an existing courtyard database on this machine (used as is, with the way to start from
nothing), and LaunchAgents that ran the hub from another directory (this install takes
them over; the other directory no longer starts anything at login, its files stay).

Install also puts a **Courtyard icon in the menu bar**: Courtyard Admin, its own small
app beside the hub (a second LaunchAgent, `com.courtyard.tray`). Its menu has the buttons
for everything below: Open WebUI, Start hub, Stop hub, Restart hub, Start shift, End
shift, Show hub log, Quit Courtyard Admin.
Beside the icon: nothing while all is quiet, the number of messages waiting at the gate
when something needs you, a hollow dot when the hub is down. The menu bar app is what
starts a hub that is down; the WebUI cannot, and it has no stop button on purpose, so the
hub stays the same program whether it runs here or, later, on another machine. It lives
in the menu bar only: no Dock tile, no entry under Cmd-Tab or Force Quit. **Quit
Courtyard Admin** takes the icon away until you want it back (killing the process instead
brings it back within seconds: launchd keeps both LaunchAgents alive). To bring it back,
open **Courtyard Admin** from Spotlight, the Dock or any launcher (it is an app in
`~/Applications`), or run `make hub-start`; it also returns at the next login. Quitting
the menu bar app never touches the hub.

| command | what it does |
|---|---|
| `make hub-status` | are the LaunchAgents loaded, is the hub answering |
| `make hub-stop` | unload: the hub stays down until `hub-start` |
| `make hub-start` | load: the hub starts, and again at every login |
| `make hub-restart` | restart under launchd (`launchctl kickstart -k`); the Admin page's restart button asks the hub itself to exit, and launchd starts it again |
| `make hub-open` | open the WebUI as its own window: the Dock app if you added one, else Chrome in app mode, else the default browser |
| `make tray` | run the menu bar app by hand (install runs it at login) |
| `make uninstall` | remove both LaunchAgents and `~/Applications/Courtyard Admin.app`, stop the containers, delete `.venv`; the data volume and `.env` stay |
| `make uninstall PURGE=1` | the same, plus the postgres volume and images |

The compose project is named `courtyard`, so the data volume is
`courtyard_courtyard-pgdata` whatever the directory is called. A clone that ran before
this name existed left two things behind: a container called `courtyard-postgres` under
the old project, which the new one cannot start beside (same name), and a volume
`cbx-agent-courtyard_courtyard-pgdata` holding a postgres 17 cluster. The data does not
carry over by copying: the image is postgres 18 now and keeps its cluster in a different
place inside the volume, so a copied volume is ignored and an empty database starts.
Either register the agents again (each project directory keeps its config; write the
files again from the WebUI), or take a dump from the old container first and load it
into the new postgres before the hub's first start:

```sh
docker start courtyard-postgres
docker exec courtyard-postgres pg_dump -U courtyard courtyard > courtyard.sql
docker rm -f courtyard-postgres   # the old project's container; the new one takes its name
make db-up                        # the new postgres, empty
docker exec -i courtyard-postgres psql -U courtyard courtyard < courtyard.sql
make run                          # or make install; the hub applies the newer migrations
```

Uninstall lists the agents' project directories first: they hold the files registration
wrote (`.mcp.json`, the settings profile, the start script), and `courtyard-invite
--remove --keep-registration` takes them out per agent while the hub is still up (without
the flag the agent is removed from the hub as well). `make zip-package` produces the zip from a checkout,
in the checkout's root, named after the git version.

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

After **add agent** the page shows the launch config. Press **write the files into
‹dir›** and the hub writes three files into the project directory: `.mcp.json` with
the agent's token (permissions 600, do not commit it), a `.claude/settings.local.json`
profile that pre-approves the courtyard tools, sets the model and a status line, and
holds one session-start hook, and `start-with-courtyard.sh`, the script that starts the
agent by hand with the channel flag it needs to hear the hub.

The hook runs once each time a session starts (or resumes, clears or compacts) and
gives it a short block of context: that this project is registered as agent so-and-so
of your team, that the hub's messages arrive through the channel named `courtyard`,
what kinds of message to expect, and that the delivery check at the start of a shift is
expected. Without it a session in a fresh directory has nothing on its own side saying
it belongs to a team, and Claude Code presents every channel event as untrusted; a
cautious model then refuses the delivery check and the first peer question. The text
comes from the hub (so the names are current) and falls back to a built-in version when
the hub is down; a session start never waits on it. Read it yourself at
`GET /api/agents/<name>/session-context`.

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
  ours), takes the courtyard entries out of `.claude/settings.local.json` (the allow
  rule, the status line, the session-start hook) and removes the start script.

From a terminal, `courtyard-invite --name <agent-name> --remove` does the same in the
same order: the directory cleanup, then the agent is removed from the hub. Add
`--keep-registration` to take the files out and leave the agent registered.

**What registration writes, and git.** The launch config panel and `courtyard-invite`
end with a notice naming the files: `.mcp.json` holds the token, the settings profile is
this machine's, a replaced file is kept beside it as `*.courtyard-bak` and can hold a
previous token; the start script carries no secret and may be committed. When the
project directory is a git checkout, the hub adds the token-carrying names to its
`.gitignore` (created if missing, in place, once) and the notice says so; removal takes
those lines out again. A directory without `.git` is left alone.

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
  starts empty. Removing an agent archives its lines by itself. Deleting an archive
  deletes the case files distilled from it (see Memory); the confirmation names how
  many.

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

## Memory

The hub keeps what happened between the agents and what you ruled; it never reads an
agent's own files. Two kinds of record live on the **Memory** page:

- **Case files.** When a thread closes (the agent that opened it calls
  `courtyard_close_thread`), the hub files the exchange: who asked, what was settled,
  every verdict with its comment, and the messages. Threads the shift expired never
  become case files.
- **Notes.** An agent deposits a lesson with `courtyard_note`, for one line (the
  peer it names, or its only line) or team-wide. A note on a supervised line, or any
  team-wide note, waits for you under **Notes waiting for you** on the Memory page:
  approve, return with a comment, or drop, the same verdicts as the gate. Returned and
  dropped notes reach their author as a hub notice. Your own notes, written with
  **+ write a note**, are accepted at once and team-wide unless you scope them.

Agents read memory with `courtyard_recall(question)`: a bounded listing (Admin,
**Recall returns** and **Recall trims to**) of the best matches among what that agent
may see, ranked by the ask, a note's body and the participants' declared domains; a
handle in the listing fetches the full case file. Under `manual` discovery an agent
recalls only from the lines it is party to; a line's note reaches that line's two
agents. You see everything on the Memory page: search, filter by participant, and read
any record in full. Recall is full text unless similarity search is configured (Hub
Administration, below).

**Export.** The raw memory for other systems: **export JSON Lines** on the Memory page,
or `GET /api/memory/export`, gives every record in full, one JSON document per line,
oldest first. Superseded records and notes in every state are included with their
status. The query parameters `participant`, `line` and `since` narrow it; `since` is
how an external system pulls only what is new.

**Retention.** A case file lives as long as the archive it was distilled from: deleting
an archive on the Archive page deletes its case files, and the confirmation says how
many. Notes are kept.

## Hub Administration

The **Admin** page has these sections:

- **Status**: hub health and configuration, whether a supervisor runs the hub (with a
  restart button when launchd does), counts for the courtyard, and two links for
  looking under the hood: the API reference and the database browser (below).
- **Teams**: the registered charters, which one is current, each team's last load
  report, its agents and links, and **reload from disk**.
- **Settings, Team**: Team mode (only `On shift` is available in v1) and Discovery
  (`auto` or `manual`, see Communication Lines).
- **Terminal application**: the app Start shift opens agents in, and the list of custom
  start strings. A custom start string must contain `{command}`, where the agent's
  launch command goes, and may contain `{dir}`. Its name may not shadow a built-in.
- **Defaults**: the mode new lines start in; the thread budget (messages per thread
  before the hub locks it; 0 means no budget); **Recall returns**, how many records one
  `courtyard_recall` call may return; **Recall trims to**, how many characters of the
  ask and the resolution a listing shows.
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
embeds records in the background, a batch every 15 seconds (`COURTYARD_EMBED_SWEEP_SECONDS`), and the Memory page shows how
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
