# Instructions for AI agents

This file is for an AI agent working in this repository: setting courtyard up
for its operator, or contributing to the code. The [README](README.md) explains
what the project is and why; this file is the executable part.

## What you are setting up

Agent Courtyard is a local communication hub for a team of AI agents: a Python
hub (FastAPI + Postgres) that carries, records and optionally gates every
message between agents, with a WebUI for the human operator. The hub binds to
`localhost` only.

## Install and start the hub

Requirements: macOS, [uv](https://docs.astral.sh/uv/), Docker with compose,
and Claude Code (`claude` on PATH) for the agents themselves. Agents of type `pi`
additionally need the pi coding agent installed
(`npm i -g @earendil-works/pi-coding-agent`).

```sh
git clone https://github.com/vkuusk/cbx-agent-courtyard.git
cd cbx-agent-courtyard
cp .env.default .env   # local settings; the compose postgres listens on 26432 (COURTYARD_PG_PORT)
uv sync
make run            # postgres + the hub on http://127.0.0.1:2626 (foreground)
```

`make run-chrome` instead starts the hub in the background (log:
`sandbox/courtyard.log`) and opens the WebUI in its own Chrome window;
`make run-stop` ends that background hub.

Verify: `curl -sf http://127.0.0.1:2626/api/health` returns success.

For day-to-day use instead of `make run`: `make install` (or, from an empty directory,
`curl -fsSL https://raw.githubusercontent.com/vkuusk/cbx-agent-courtyard/main/install.sh | sh`,
which downloads the newest release and runs it) registers the hub as a macOS
LaunchAgent (starts at login, restarts on exit) plus a second one for Courtyard Admin,
the icon in the menu bar (two files under `~/Library/LaunchAgents`, `com.courtyard.hub`
and `com.courtyard.tray`, and `~/Applications/Courtyard Admin.app`, the launcher that
brings the menu bar icon back after Quit Courtyard Admin); the menu has the buttons Open
WebUI, Start / Stop / Restart hub, Start / End shift, Show hub log, Quit Courtyard Admin. The install
runs six numbered steps and ends with a Summary block:
one line per step, OK or WARNING, every warning repeated in full. Read it and report
any warning to your operator; the two it knows are an EXISTING courtyard database
(one database per machine by design, shared by every checkout and install; the block
names how to start from nothing) and LaunchAgents taken over from another directory
(that directory no longer starts the hub at login). The WebUI asks once whether to keep
it in the Dock; when the Dock app already exists the install opens that instead.
`make hub-status`, `hub-stop`, `hub-start`, `hub-restart`; `make uninstall` reverses it.

## Register the team's agents

Ask your operator for the team design first; see the next section. The hub
requires a current team before any agent can be registered: the team's charter
directory is where the team definition lives as files (its own directory,
outside every agent's workdir, ideally its own git repo). The first
registration carries it; after that one command per agent registers it and
writes its config:

```sh
# first agent: choose the team's charter directory in the same command
# (an empty directory is initialized as a charter)
uv run courtyard-invite --team-dir <the team's charter directory> \
    --team-name <team-name> \
    --register --name <agent-name> \
    --description "<what the agent can do>" \
    --sme-domain "<what the agent owns>" \
    --anti-scope "<what NOT to ask this agent>" \
    --workdir <the agent's project directory> \
    --model sonnet    # optional; the model the agent should run

# every further agent: the team is already current, drop the --team flags
uv run courtyard-invite --register --name <agent-name> ...
```

Each registration is also written into the charter directory as that agent's
card files, so the team definition stays reviewable and portable.

This writes three files into the workdir: `.mcp.json` (holds the agent's hub
token, permissions 600, must not be committed), a `.claude/settings.local.json`
profile that pre-approves the courtyard tools and carries a session-start hook telling
the session it is a member of the team, and `start-with-courtyard.sh`, the
script a human runs to start this agent by hand (it carries the channel flag; a
bare `claude` session cannot hear the hub). When the workdir is a git checkout the
hub adds the token-carrying names to its `.gitignore` and says so; the start script
may be committed. Undo with `courtyard-invite --name <agent-name> --remove`: the
files come out and the agent leaves the hub (add `--keep-registration` to detach the
directory only).

Verify the whole message path without any real agents: `make demo` runs two
scripted dummy agents through the hub, including a supervised gate;
`make demo-stop` removes the dummies and everything they produced.

## Decisions that belong to your operator

Do not invent these; ask.

- **Team composition**: which agents, split how. This is the most important
  input to the whole setup.
- **The team's charter directory** (`--team-dir`) and name: where the team
  definition lives as files. Outside every agent's workdir; typically its own
  git repo.
- **Per agent, the descriptive fields**: what it can do (`--description`,
  advertised to every other agent), what it owns (`--sme-domain`, marks the
  agent's word as authoritative inside its own area), and optionally what it is
  not for (`--anti-scope`, tells peers whom not to ask).
- **Names**: an agent's name cannot be renamed later. A removed agent's name can
  be registered again; that revives the agent's record with a new token.

## Steps only a human can do

Stop and hand these off; report exactly what remains.

- Starting the agents: **Start shift** on the WebUI's Courtyard page opens one
  terminal per agent (Terminal, iTerm2 or Ghostty, chosen under Admin), already
  connected. At each agent's first launch, Claude Code asks two trust questions
  in its terminal; they cannot be pre-answered. Answer yes to both: a refused MCP
  question is remembered in the workdir's `.claude/settings.local.json` as a
  `disabledMcpjsonServers` entry, and the agent then never reaches the hub.
- Supervising: gate verdicts (approve, return to sender, drop) are given on the
  WebUI by the operator.

When setup is done, point your operator at [docs/quickstart.md](docs/quickstart.md),
the full walkthrough with every screen described, and at
[docs/user-guide.md](docs/user-guide.md), the operator's reference.

## Contributing to the code

- Setup: `uv sync`. The automated bar for any change is `make check` (test
  suite + lint; needs Docker, brings postgres up itself). `make fmt` fixes
  formatting.
- The full testing workflow (which checks to run, which tests a change must
  add, gotchas) is a skill: read
  [.claude/skills/courtyard-testing/SKILL.md](.claude/skills/courtyard-testing/SKILL.md)
  before testing or adding tests. Claude Code loads it by itself.
- Every completed feature ships a manual verification procedure in
  `docs/testing-runbook.md` plus a durable script in `scripts/runbook/`;
  conventions live in `docs/developer-notes.md`.
- The design document (`docs/design/architecture-v1.md`) records
  every decision with its reasons in a decision log; read the relevant entries
  before proposing a design change.
- User-facing docs (README, `docs/`) never use the em dash character; write in
  a plain, honest technical register.