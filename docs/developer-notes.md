# Developer notes

Standing conventions for working on courtyard. These are standards, not suggestions —
follow them unless a change is agreed with the architect.

## Every feature ships with a manual test procedure

When an implementation step (or any feature that changes observable behaviour) is complete,
add a procedure to [`testing-runbook.md`](testing-runbook.md). This is part of "done",
alongside green `make test` and clean `make lint` — not a follow-up.

**Runbook entry format** (keep it terse — checkpoints, not prose):

```
## <section name>

**Feature under test:** one or two sentences, with the design-doc reference (§ / D-number).

**Run:**
    <copy-paste command>            # omit this block if no single command applies

**Expected:** what the operator should see — the specific values that confirm it works.
```

**Walkthrough scripts** backing a `Run:` command:

- Live in `scripts/runbook/`, one file per procedure. They are durable repo files, never
  left in a scratch dir.
- Held to the same bar as `src/` — `make lint` covers `scripts/`, so they stay ruff-clean.
- Self-contained and self-cleaning: register throwaway agents with unique names (a time
  suffix), remove them at the end, and don't depend on prior runs. Exit 0 on success.
- **Print the checkpoints**, don't just assert them. The value over `make test` is that the
  operator reads the actual output (the envelope text, the peers listing) with their own
  eyes. Automated tests assert; runbook scripts show.
- Use the real client library and real endpoints (`courtyard.common.client`), so what prints
  is what a real agent would receive.

**Before handing a procedure to the architect, run it yourself** against a live hub
(`make db-up && make run`) and confirm it works end to end. Never present a command unrun.

**Automated tests remain the proof of logic; the runbook is for seeing it work.** Both, not
either. The runbook also doubles as living documentation of how each feature behaves.
