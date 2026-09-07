"""Runbook check: the team charter registry, slice 1 (design team-charter.md, D33).

Runs against its OWN throwaway hub on a scratch database — never the dev hub — because
registering teams and choosing the current one is courtyard-wide state.

  1. add the committed demo charter (tests/team-charter): name and three agents load
  2. the report is empty; what the hub cached is what the files say
  3. initialize: a directory without team-definition.yml draws the name offer (the
     name confirms), then the hub writes the index; existing files are untouched
  4. the hub never watches the filesystem: an edit shows only after reload
  5. a broken charter reloads into a readable report, the row survives
  6. current-team selection: exactly one current; clearing works; remove leaves files

Needs the compose postgres up (`make db-up`). Run:
    uv run python scripts/runbook/team_charter.py
"""

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from courtyard.common.client import HubClient, HubError

PORT = 3635
HUB = f"http://127.0.0.1:{PORT}"
DB_NAME = "courtyard_teams_rb"
PG_PORT = os.environ.get("COURTYARD_PG_PORT", "5432")
DB = f"postgresql://courtyard:courtyard@127.0.0.1:{PG_PORT}/{DB_NAME}"
FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "team-charter"


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
    env = {**os.environ, "DATABASE_URL": DB, "COURTYARD_PORT": str(PORT)}
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
scratch = Path(tempfile.mkdtemp(prefix="courtyard-charter-rb-"))
try:
    hr("1. ADD THE DEMO CHARTER (tests/team-charter)")
    team = admin.add_team(str(FIXTURE))
    print(f"name              : {team.name}")
    print(f"agents            : {[a.name for a in team.charter.agents]}")
    print(f"report            : {team.load_report or 'clean'}")
    infra = team.charter.agents[0]
    hr("2. WHAT THE HUB CACHED IS WHAT THE FILES SAY (agent `infra`)")
    print(f"type/model/color  : {infra.type} / {infra.model} / {infra.color}")
    print(f"description       : {infra.description}")
    print(f"owns              : {infra.sme_domain}")
    print(f"anti-scope        : {infra.anti_scope}")

    hr("3. INITIALIZE A DIRECTORY WITHOUT A CHARTER (empty or not)")
    empty = scratch / "fresh-team"
    empty.mkdir()
    (empty / "notes.txt").write_text("already here\n")
    try:
        admin.add_team(str(empty))
        print("BUG: a charter-less dir was added without a name")
    except HubError as exc:
        print(f"no name           : answered {exc.code}  <- the UI offers to initialize on this")
    fresh = admin.add_team(str(empty), name="fresh-team")
    print(f"with a name       : initialized; the hub wrote {empty / 'team-definition.yml'}")
    print(f"existing file     : untouched ({(empty / 'notes.txt').read_text().strip()!r})")
    print("the index         :")
    print((empty / "team-definition.yml").read_text())

    hr("4. THE HUB NEVER WATCHES: EDITS LAND AT RELOAD")
    (empty / "team-definition.yml").write_text("team:\n  name: renamed-team\n  agents: {}\n")
    print(f"after the edit    : hub still says {admin.teams()[1].name!r}")
    fresh = admin.reload_team(fresh.id)
    print(f"after reload      : hub says {fresh.name!r}, loaded_at {fresh.loaded_at}")

    hr("5. A BROKEN CHARTER BECOMES A REPORT, NOT AN ERROR")
    (empty / "team-definition.yml").write_text("team: [broken")
    fresh = admin.reload_team(fresh.id)
    print(f"report            : {fresh.load_report}")
    print(f"row survives      : name still {fresh.name!r}, charter cached: {fresh.charter}")

    hr("6. CURRENT TEAM: EXACTLY ONE, CLEARABLE; REMOVE LEAVES THE FILES")
    teams = admin.set_current_team(team.id)
    print(f"current flags     : { {t.name: t.is_current for t in teams} }")
    teams = admin.set_current_team(None)
    print(f"after clearing    : { {t.name: t.is_current for t in teams} }")
    admin.remove_team(fresh.id)
    print(f"after remove      : {[t.name for t in admin.teams()]} registered")
    print(f"files stayed      : {(empty / 'team-definition.yml').is_file()}")
finally:
    admin.close()
    hub.terminate()
    hub.wait()
    psql(f"DROP DATABASE IF EXISTS {DB_NAME} WITH (FORCE)")
    print("\n(throwaway hub stopped, scratch database dropped; scratch dir left in /tmp.)")
