"""Runbook check: the stale shift and its question (design §8.1, D25).

Runs against its OWN throwaway hub on a scratch database — never the dev hub — because
producing a stale shift means seeding the shift document directly. The seeded window
refs point at a tty that does not exist, so nothing real is ever opened or closed; the
script never calls resume/start on the stale shift (those would spawn real terminals —
that is the manual procedure in docs/testing-runbook.md).

  1. a shift document says `on`, every agent is offline, every window is dead
     -> after the liveness grace, GET /api/shift reports stale: true
  2. an agent marked connected -> stale: false (a mid-shift hub restart never asks)
  3. End shift on the stale shift -> off; the vanished window is skipped, books close
  4. resume with no shift open -> 409 no_shift

Needs the compose postgres up (`make db-up`). Run:
    uv run python scripts/runbook/stale_shift.py
"""

import json
import os
import subprocess
import sys
import time

from courtyard.common.client import HubClient, HubError

PORT = 3633
HUB = f"http://127.0.0.1:{PORT}"
DB_NAME = "courtyard_stale_rb"
DB = f"postgresql://courtyard:courtyard@127.0.0.1:5432/{DB_NAME}"
HEARTBEAT = "1"  # liveness grace = heartbeat + 5s margin -> stale flips ~6s after start


def hr(title):
    print("\n" + "=" * 78 + f"\n{title}\n" + "=" * 78)


def psql(*statements, db="postgres"):
    subprocess.run(
        ["docker", "exec", "courtyard-postgres", "psql", "-U", "courtyard", "-d", db]
        + [arg for s in statements for arg in ("-c", s)],
        check=True,
        capture_output=True,
    )


def start_hub():
    env = {
        **os.environ,
        "DATABASE_URL": DB,
        "COURTYARD_PORT": str(PORT),
        "COURTYARD_HEARTBEAT_SECONDS": HEARTBEAT,
    }
    proc = subprocess.Popen(
        ["uv", "run", "courtyard-hub"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    client = HubClient(HUB)
    for _ in range(60):
        try:
            client._call("GET", "/api/health")
            return proc, client
        except (HubError, Exception):  # noqa: BLE001 - connection refused while booting
            time.sleep(0.2)
    proc.terminate()
    sys.exit("throwaway hub did not start")


psql(f"DROP DATABASE IF EXISTS {DB_NAME} WITH (FORCE)", f"CREATE DATABASE {DB_NAME}")
hub, admin = start_hub()
try:
    hr("SEED  (a shift left open: doc says on, agent offline, window tty dead)")
    agent, _ = admin.register_agent("coder", "claude-code", workdir="/tmp/coder")
    hub.terminate()
    hub.wait()
    doc = {
        "state": "on",
        "started_at": "2026-08-25T09:00:00+00:00",
        "terminal_app": "Terminal",
        "spawned": True,
        "skipped": [],
        "spawns": [
            {
                "agent_id": str(agent.id),
                "agent_name": "coder",
                "window_ref": json.dumps(
                    {"app": "Terminal", "window_id": "999999", "tty": "/dev/ttys987"}
                ),
                "spawned_at": "2026-08-25T09:00:10+00:00",
            }
        ],
    }
    psql(
        "INSERT INTO settings (key, value) VALUES ('shift', '" + json.dumps(doc) + "')",
        "UPDATE agents SET status = 'connected' WHERE name = 'coder'",  # yesterday's claim
        "INSERT INTO channels (agent_id, endpoint, channel_token, last_heartbeat)"
        f" VALUES ('{agent.id}', 'http://127.0.0.1:9/push', 'ct', now() - interval '12 hours')",
        db=DB_NAME,
    )
    admin.close()
    hub, admin = start_hub()  # the "next morning": hub starts into the seeded shift
    print("hub restarted into the seeded shift")

    hr("1. CHECKING FIRST (D26), THEN STALE — ONE TRANSITION")
    status = admin._call("GET", "/api/shift")
    coder = next(a for a in admin.agents() if a.name == "coder")
    print(
        f"right after start : agent={coder.status} stale={status['stale']}"
        f" checking_until={'set' if status['checking_until'] else 'None'}"
        "   <- unknown, no claims, no question yet"
    )
    deadline = time.time() + 15
    while not status["stale"] and time.time() < deadline:
        time.sleep(0.5)
        status = admin._call("GET", "/api/shift")
    coder = next(a for a in admin.agents() if a.name == "coder")
    print(
        f"after the grace   : agent={coder.status} state={status['state']} stale={status['stale']}"
    )

    hr("2. A CONNECTED AGENT MEANS NOT STALE  (mid-shift restart never asks)")
    psql("UPDATE agents SET status = 'connected' WHERE name = 'coder'", db=DB_NAME)
    print(f"agent connected   : stale={admin._call('GET', '/api/shift')['stale']}")
    psql("UPDATE agents SET status = 'gone' WHERE name = 'coder'", db=DB_NAME)
    time.sleep(1.5)
    print(f"agent gone again  : stale={admin._call('GET', '/api/shift')['stale']}")

    hr("3. END SHIFT RESOLVES IT  (the vanished window is skipped, books close)")
    status = admin._call("POST", "/api/shift/end", {"force": True})
    print(f"after end         : state={status['state']} stale={status['stale']}")

    hr("4. RESUME WITH NOTHING OPEN IS REFUSED")
    try:
        admin._call("POST", "/api/shift/resume")
        print("resume            : ACCEPTED — that is a bug")
    except HubError as exc:
        print(f"resume            : refused ({exc})")
finally:
    admin.close()
    hub.terminate()
    hub.wait()
    psql(f"DROP DATABASE IF EXISTS {DB_NAME} WITH (FORCE)")
    print("\n(throwaway hub stopped, scratch database dropped.)")
