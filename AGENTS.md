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
cp .env.default .env   # local settings; if port 5432 is taken, set COURTYARD_PG_PORT here
uv sync
make run            # postgres + the hub on http://127.0.0.1:2626 (foreground)
```

`make run-chrome` instead starts the hub in the background (log:
`sandbox/courtyard.log`) and opens the WebUI in its own Chrome window;
`make run-stop` ends that background hub.

Verify: `curl -sf http://127.0.0.1:2626/api/health` returns success.

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
profile that pre-approves the courtyard tools, and `start-with-courtyard.sh`, the
script a human runs to start this agent by hand (it carries the channel flag; a
bare `claude` session cannot hear the hub). Undo with the same command using
`--remove` instead of `--register`.

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
- **Names**: an agent's name is a permanent identity on the hub; it cannot be
  renamed later.

## Steps only a human can do

Stop and hand these off; report exactly what remains.

- Starting the agents: **Start shift** on the WebUI's Courtyard page opens one
  terminal per agent, already connected. At each agent's first launch, Claude
  Code asks two trust questions in its terminal; they cannot be pre-answered.
- Supervising: gate verdicts (approve, return to sender, drop) are given on the
  WebUI by the operator.

When setup is done, point your operator at [docs/quickstart.md](docs/quickstart.md),
the full walkthrough with every screen described.

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