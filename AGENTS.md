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
and Claude Code (`claude` on PATH) for the agents themselves.

```sh
git clone https://github.com/vkuusk/cbx-agent-courtyard.git
cd cbx-agent-courtyard
uv sync
make run            # postgres + the hub on http://127.0.0.1:2626 (foreground)
```

`make run-chrome` instead starts the hub in the background (log:
`sandbox/courtyard.log`) and opens the WebUI in its own Chrome window;
`make run-stop` ends that background hub.

Verify: `curl -sf http://127.0.0.1:2626/api/health` returns success.

## Register the team's agents

Ask your operator for the team design first; see the next section. Then, for
each agent, one command registers it and writes its config:

```sh
uv run courtyard-invite --register --name <agent-name> \
    --description "<what the agent can do>" \
    --sme-domain "<what the agent owns>" \
    --workdir <the agent's project directory> \
    --model sonnet    # optional; the model the agent should run
```

This writes two files into the workdir: `.mcp.json` (holds the agent's hub
token, permissions 600, must not be committed) and a `.claude/settings.local.json`
profile that pre-approves the courtyard tools. Undo with the same command using
`--remove` instead of `--register`.

Verify the whole message path without any real agents: `make demo` runs two
scripted puppet agents through the hub, including a supervised gate;
`make demo-stop` removes the puppets and everything they produced.

## Decisions that belong to your operator

Do not invent these; ask.

- **Team composition**: which agents, split how. This is the most important
  input to the whole setup.
- **Per agent, two descriptive fields**: what it can do (`--description`,
  advertised to every other agent) and what it owns (`--sme-domain`, marks the
  agent's word as authoritative inside its own area).
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

- Setup: `uv sync`. Tests: `make test` (needs Docker; brings postgres up
  itself). Lint: `make lint`, format: `make fmt`. Both must pass.
- Every completed feature ships a manual verification procedure in
  `docs/testing-runbook.md` plus a durable script in `scripts/runbook/`;
  conventions live in `docs/developer-notes.md`.
- The design document (`docs/design/architecture-v1-2026-08-18.md`) records
  every decision with its reasons in a decision log; read the relevant entries
  before proposing a design change.
- User-facing docs (README, `docs/`) never use the em dash character; write in
  a plain, honest technical register.