"""Runbook check: a terminal spawner opens a window, proves it alive, and closes it
along with what was running in it (design §8.1, D23/D25/D33).

Drives one spawner directly — no hub, no agents, no settings touched, so it is safe to
run while the dev hub and a live shift are up. What it walks:

  1. spawn: a window opens, `cd`-ed into the workdir, running a harmless marker command
     (never a real agent's launch command) — the ref carries the window id and the tty
  2. alive: the tty probe sees the running process (this is D25's "the window sits open"
     signal, and the `ps -t` form is what makes it work on macOS 26 — `pgrep -t` there
     matches nothing and read every window as dead)
  3. close: the marker process is ended FIRST, then the window closes — no confirmation
     dialog, and nothing is left running behind the operator's back
  4. after: the window is gone, alive reads false, no orphaned marker process

Run it once per terminal application you support:

    uv run python scripts/runbook/terminal_spawners.py            # Ghostty
    uv run python scripts/runbook/terminal_spawners.py Terminal
    uv run python scripts/runbook/terminal_spawners.py iTerm2

Watch the screen as well as the output: a window must appear and then vanish.
"""

import json
import subprocess
import sys
import time

from courtyard.common.models import BUILTIN_TERMINALS
from courtyard.hub.core.spawn import make_spawner

MARKER = f"courtyard-runbook-{int(time.time())}"
WORKDIR = "/tmp"
# stands in for the agent's launch command; the marker rides in the process's own argv
# so this script can tell whether the window really took its process with it
COMMAND = f"sh -c 'echo {MARKER}; sleep 300'"


def hr(title):
    print("\n" + "=" * 78 + f"\n{title}\n" + "=" * 78)


def marker_pids():
    out = subprocess.run(
        ["pgrep", "-f", MARKER], capture_output=True, text=True, check=False
    ).stdout
    return [pid for pid in out.split() if pid]


app = sys.argv[1] if len(sys.argv) > 1 else "Ghostty"
if app not in BUILTIN_TERMINALS:
    sys.exit(f"{app!r} is not one of the built-in terminals: {', '.join(BUILTIN_TERMINALS)}")
spawner = make_spawner(app)
print(f"application   : {app} ({type(spawner).__name__})")
print(f"marker        : {MARKER}")

hr("1. SPAWN  (a window must appear)")
ref = spawner.spawn(WORKDIR, COMMAND)
print(f"ref           : {ref}")
if ref is None:
    sys.exit("no window reference — this application only opens windows (custom app)")
info = json.loads(ref)
print(f"window id     : {info['window_id']}")
print(f"tty           : {info['tty'] or 'NOT REPORTED — liveness and close cannot work'}")
time.sleep(1)
print(f"marker running: {marker_pids() or 'NO — the command never started'}")

hr("2. ALIVE  (D25: an open window must not read as abandoned)")
print(f"alive()       : {spawner.alive(ref)}   (expected True)")
if info["tty"]:
    name = info["tty"].removeprefix("/dev/")
    print(f"ps -t {name}:")
    print(subprocess.run(["ps", "-t", name], capture_output=True, text=True, check=False).stdout)

hr("3. CLOSE  (the process ends first, then the window — no dialog)")
print(f"close()       : {spawner.close(ref)}   (expected True)")
time.sleep(1)

hr("4. AFTER")
print(f"alive()       : {spawner.alive(ref)}   (expected False)")
leftovers = marker_pids()
print(f"orphans       : {leftovers or 'none — the window took its process with it'}")
if leftovers:
    print("  ^ FAILING: end shift would leave the agent running. Kill them:")
    print(f"    pkill -f {MARKER}")
print("\nOn screen: the window appeared in step 1 and is gone after step 3.")
