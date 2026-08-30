---
name: courtyard-testing
description: Testing workflow for the cbx-agent-courtyard repository. How to run the existing checks (pytest suite, lint, runbook scripts, live round-trip, WebUI checks) and which tests a change must add. Use when verifying or testing a change, adding tests for new code, writing a testing-runbook entry, or when a check needs a safe throwaway hub.
compatibility: Requires uv and Docker with compose. Live-session checks additionally need Claude Code on PATH (macOS).
---

# Testing courtyard

## The layers, and when each runs

1. **`make check`**: the automated bar for every change: the full pytest suite
   plus lint (`make fmt` fixes formatting). The suite runs against a dedicated
   `courtyard_test` database in the compose postgres (brought up
   automatically), so dev data is never touched. Pytest discovers every
   `tests/test_*.py` file by itself; there is no suite list to maintain. Must
   pass before a change is done.
2. **Runbook scripts** in `scripts/runbook/`: manual verification procedures
   that print what the operator would see. Run the one covering the feature
   area you changed; read its header first, some need their own throwaway hub.
3. **`make test-comms`**: proves the operator to live-Claude-Code-session round
   trip. Run it only when the adapter, envelope, or delivery path changed, or
   after a Claude Code auto-update; it launches a real session (needs `claude`
   on PATH and model access).
4. **WebUI browser check**: drive the changed pages with Playwright against
   `make demo` or a scratch hub. The bar is the flow working with zero browser
   console errors.

## What a change must add

- **Hub logic or API**: tests in `tests/test_<area>.py` using the fixtures in
  `tests/conftest.py` (real postgres, real app). Follow the neighbouring tests'
  style.
- **A new migration**: a test that exercises it. If it rewrites rows, verify it
  against a database seeded with pre-migration data, not only against a fresh
  schema.
- **WebUI change**: a Playwright drive of the changed flow, checking rendered
  state and console errors.
- **Every completed feature**: a runbook entry plus a durable script (next
  section). This is part of "done", not a follow-up.

## The runbook standard

The standard is defined in `docs/developer-notes.md`; the entries live in
`docs/testing-runbook.md`; the scripts live in `scripts/runbook/`.

- Before changing an existing feature, read its runbook entry: it states the
  feature's observable behaviour and how to verify it.
- A runbook script prints its checkpoints rather than just asserting them; the
  point is that the operator reads real output (the envelope text, the peers
  listing) with their own eyes. Use the real client (`courtyard.common.client`)
  so what prints is what a real agent would receive.
- Entries are terse: checkpoints, not prose. Copy the format of an existing
  entry.
- Run your new procedure yourself before handing it to the operator.

## When a check needs its own hub

Any check that flips courtyard-wide settings (discovery, defaults, team mode)
or does destructive data work must run on a throwaway hub, never the dev hub.
Do not improvise a hub launch; run exactly:

```sh
uv run python .claude/skills/courtyard-testing/scripts/scratch_hub.py start --name <check-name>
# ... run the check against the printed URL (pass it as COURTYARD_HUB_URL or --hub) ...
uv run python .claude/skills/courtyard-testing/scripts/scratch_hub.py stop --name <check-name>
```

It creates a scratch database, starts a hub on a free port, and `stop` removes
both. `scripts/runbook/discovery_links.py` and `stale_shift.py` show the full
pattern in use.

## Gotchas

- **Port 2626 is the operator's live hub.** Never kill it, restart it, or flip
  its courtyard-wide settings; live agents are attached and a settings flip
  refuses their sends mid-run. Never `pkill -f courtyard-hub`; stop only pids
  you recorded (the scratch hub script and `make run-stop` do this correctly).
- **Live-session tests steal channels.** An attach for an agent name takes over
  that agent's channel (last attach wins), so tests that launch sessions must
  use throwaway agent names on a throwaway hub, never a real agent's name or
  token.
- **Agent names are permanent identities** on a hub. Test registrations need
  unique throwaway names and must clean up after themselves (`scripts/demo.py`
  shows the cast-cleanup pattern).
- **Playwright is deliberately not a project dependency.** Install it in a
  venv outside the repo. In the WebUI, the clickable line row is `button.line`
  (`.wire` is only the middle span), and `agent_a` of a pair is not
  registration order.
- **Do not wrap streaming responses in generic HTTP middleware**; it makes SSE
  tests flaky. Static-file headers are handled in `RevalidatingStaticFiles`.
- **If live messages stop after a Claude Code auto-update**, run
  `make test-comms` before blaming the hub; the channels research preview's
  flag contract has drifted before, and the test prints whether the channel
  was registered or skipped.