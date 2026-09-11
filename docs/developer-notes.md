# Developer notes

Standing conventions for working on courtyard. These are standards, not suggestions —
follow them unless a change is agreed with the architect.

## How testing is organized

Three layers, each with one entry point:

- **Functional tests**: `tests/test_*.py`, run by `make test` against a dedicated
  `courtyard_test` database in the compose postgres, so dev data is never touched.
  Pytest discovers every `test_*.py` file automatically; there is no suite list to
  maintain.
- **End-to-end**: `tests/communications/`, run by `make test-comms` on demand. It
  drives a live Claude Code session, so it needs `claude` on PATH and is not part
  of `make test`.
- **Manual verification**: `scripts/runbook/` scripts plus their entries in
  [`testing-runbook.md`](testing-runbook.md), run by a human per feature (next
  section). These show; they are not automated tests and do not live in `tests/`.

`make check` runs the automated "done" bar: the functional suite plus lint.

## Every feature ships with a manual test procedure

When an implementation step (or any feature that changes observable behaviour) is complete,
add a procedure to [`testing-runbook.md`](testing-runbook.md). This is part of "done",
alongside a green `make check` — not a follow-up.

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
(`make run`) and confirm it works end to end. Never present a command unrun.

**Automated tests remain the proof of logic; the runbook is for seeing it work.** Both, not
either. The runbook also doubles as living documentation of how each feature behaves.

## The WebUI is served with `Cache-Control: no-cache`

`webui/` is plain files that change with every edit, and the browser loads them as ES
modules that import each other. Without a cache header a normal reload can take some
modules from the browser cache and others fresh — the page then runs a mix of old and new
code and fails in confusing ways ("Loading…" forever, a control that does not react).
The hub therefore sends `Cache-Control: no-cache` for everything outside `/api/`: the
browser always revalidates, the `ETag` makes that a cheap 304, and a normal reload is
enough after any change. If a browser tab was open *before* this header existed, one
hard reload (Cmd+Shift+R) clears what it cached.

## Releasing

A release is a git tag `v<version>` on `main`; the workflow `.github/workflows/release.yml`
builds the install zip (`make zip-package`, the committed tree minus what
`.gitattributes` export-ignores) and publishes a GitHub Release with it, under the fixed
name `courtyard.zip` and the versioned name. `install.sh` downloads the newest release,
so a tag is what users get.

The version is written in two places, `pyproject.toml` and its copy in `uv.lock`, and the
tag must match them. Let uv move both at once; a hand edit of `pyproject.toml` leaves
`uv.lock` behind until the next uv command, which then changes a tracked file after the
commit.

1. On the feature branch, when it is ready to merge:

   ```sh
   uv version --bump patch        # or: uv version 0.2.0
   uv lock --check                # non-zero if the lock is behind pyproject.toml
   git add pyproject.toml uv.lock
   git commit -m "- bump version to 0.2.0"
   ```

2. Merge the branch into `main` (a pull request; `make check` green).
3. Tag the merge and push the tag; the workflow does the rest:

   ```sh
   git checkout main && git pull
   git tag v0.2.0 && git push --tags
   ```

4. Check the release page: `courtyard.zip` and `courtyard-v0.2.0.zip` attached, the
   generated notes readable. `curl -fsSL .../install.sh | sh` in an empty directory is
   the end-to-end check.

The adapter reports the same version (read from the package metadata), so the hub, the
zip and the tag never disagree.
