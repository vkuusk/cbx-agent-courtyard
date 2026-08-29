# Documentation

The root [README](../README.md) gets you running; this page is the map for everything
deeper.

## How it works, briefly

One Python hub (FastAPI + Postgres) owns all state: the agent registry, the per-pair
**lines**, every message, and the liveness picture. Agents connect through a small MCP
adapter riding Claude Code's channels preview: the hub pushes deliveries into the
agent's session and the agent answers with a `courtyard_send` tool call; nothing an
agent prints in its terminal reaches anyone. The operator usually works in the main
agent's terminal, delegating through it; the WebUI (a no-build Preact page served by
the hub, fed by server-sent events) is where the team is watched and gated.

The core ideas, each with its section in the design doc:

- **Lines and turns**: between any pair of agents there is one line, and on it at most
  one unanswered message in flight. Turn-taking is backpressure the models can reason
  about (§5.2, §5.4).
- **The gate**: each line is `supervised` (every message held for the operator's
  approve / return-to-sender / drop) or `auto_pass` (flows, still logged). Operator
  lines are never gated (§5.5, §5.6).
- **The envelope**: the hub wraps every delivery with an authority grade (operator /
  domain-owner / agent / hub-notice) and a reply-path footer, so the receiving model
  knows how much say the text has and how to answer so the sender actually hears it
  (§7.5).
- **The shift**: one button opens a terminal per registered agent and connects the
  team; ending the shift closes exactly those windows and expires unfinished
  conversations, so the books close with the working day (§8.1).
- **Discovery**: `auto` (any pair may start talking; lines form on first message) or
  `manual` (agents see and reach only whom the operator has linked, forming sub-teams) (§5.8).
- **The archive**: finished or unlinked conversations move to an immutable archive;
  the WebUI shows only live lines (§5.7).

## The documents

| Document | What it holds |
|---|---|
| [quickstart.md](quickstart.md) | Install + a worked example with two real Claude Code agents, every screen described: the permanent "new operator" path |
| [design/architecture-v1-2026-08-18.md](design/architecture-v1-2026-08-18.md) | The full design: concepts, delivery model, liveness, the shift, and a decision log (§13) recording every choice with its reasons |
| [planning/v1-implementation-steps.md](planning/v1-implementation-steps.md) | The build, step by step, with what changed and when |
| [planning/feedback-items.md](planning/feedback-items.md) | The architect's live-testing observations and what became of each |
| [testing-runbook.md](testing-runbook.md) | Manual verification procedures per feature, backed by scripts in `scripts/runbook/` |
| [developer-notes.md](developer-notes.md) | Standing engineering conventions for working on the code |

## Development setup

The basics are in the root README (`uv sync`, then `make run`, which brings postgres up itself). The notes
below matter once you work on the code.

**The demo, in more detail.** `make demo` starts the hub (unless one is running) plus
scripted puppet agents; runtime files and process logs land in `.demo/` (gitignored).
Each run registers a fresh cast with unique name suffixes, and the cast cleans up after
itself: both `make demo-stop` and a re-run remove the previous cast from the WebUI and
delete its throwaway archives, so the WebUI looks the way it did before the demo. The
demo pre-links its pairs and pins them supervised, so it runs the same whatever the
operator's Discovery / Defaults settings say. It ends with instructions for playing an
agent yourself from a second terminal (`courtyard-puppet --behavior manual`, then
`/pending`, `/approve`, `/auto`, `/help`, …).

**Python version.** Pinned in `.python-version` as `3.14`, deliberately minor-only
rather than `3.14.x`, so homebrew patch upgrades keep matching the pin instead of fighting it.
Note that `.venv` does **not** contain its own Python: on macOS every venv tool (venv,
virtualenv/PyCharm, uv) symlinks the interpreter, here via brew's `opt/python@3.14`
path. A `brew upgrade` therefore changes what the venv runs and can leave stale
versioned paths behind. After any brew Python upgrade, recreate the venv:
`rm -rf .venv && uv sync` (PyCharm keeps working; the `.venv/bin/python` path it points
at is unchanged).

**Using pip alongside uv.** The project is a standard PEP 621 `pyproject.toml`, so pip
works on the same `.venv`:

```sh
source .venv/bin/activate
pip install <something>          # fine for experiments in the existing uv-created venv
```

or fully pip-managed from scratch:

```sh
python3.14 -m venv .venv && source .venv/bin/activate
pip install -e . --group dev     # --group needs pip >= 25.1; else: pip install -e . pytest ruff
```

Use `-e` (editable): a plain `pip install .` freezes a copy of the code into
site-packages, which then shadows edits to `src/` until reinstalled.

**Run `uv sync` only for setup and after dependency changes, not casually.** It makes
the venv match `uv.lock` *exactly*, so it removes packages that were pip-installed by
hand. When a step adds project dependencies, `uv sync` will run again; re-install
personal pip extras afterwards, or make them permanent with `uv add <pkg>` (updates
`pyproject.toml` + `uv.lock` + the venv in one go). To pick up new project deps
**without** pruning your pip extras, use `uv sync --inexact`: it installs what the
lock requires and leaves the rest alone.

Lockfile maintenance: `uv lock` re-resolves `uv.lock` from `pyproject.toml` (uv never
locks from the venv state); `uv lock --upgrade` refreshes all pins within the
constraints; `uv lock --upgrade-package <name>` refreshes one.

**Local scratch space.** `sandbox/` is the gitignored experimentation area (only its
README is kept); `make run-chrome` writes its log and pid there.

## Deployment modes

- **dev_mode** (now): postgres in a container, the hub from the working tree
  (`make run` / `make run-chrome`).
- **live_mode** (post-v1, D16): hub + postgres both in containers via
  `docker compose --profile live up`.

The hub binds `127.0.0.1` only; v1 is an on-my-laptop-only deployment by design.
