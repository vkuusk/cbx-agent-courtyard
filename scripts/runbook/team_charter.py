"""Runbook check: the team charter (design team-charter.md, D33) — the read path
(slice 1), the projection into registrations and lines (slice 2), and write-back
from the agent forms (slice 3).

Runs against its OWN throwaway hub on a scratch database — never the dev hub — because
registering teams, choosing the current one and projecting a charter is courtyard-wide
state.

  1. add the committed demo charter (tests/team-charter): name and three agents load
  2. the report is empty; what the hub cached is what the files say
  3. initialize: a directory without team-definition.yml draws the name offer (the
     name confirms), then the hub writes the index; existing files are untouched
  4. the hub never watches the filesystem: an edit shows only after reload
  5. a broken charter reloads into a readable report, the row survives
  6. selecting a team as current projects it: cards become registrations (with the
     anti-scope), links become lines with their declared gate modes
  7. answering an agent's workdir writes the per-machine overlay + the registration
  8. the files are the master: an edited description lands at reload, a declared
     line mode is reasserted over a WebUI flip
  9. write-back: registering an agent while the team is current writes its yml
     entry, card files and overlay workdir; an edit lands on the card files;
     removal takes the entry, links and config dir back out — reload agrees
 10. the shift guard: the current team cannot be reloaded while a shift runs
 11. exactly one current team; clearing works; remove leaves the files

Needs the compose postgres up (`make db-up`). Run:
    uv run python scripts/runbook/team_charter.py
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import yaml

from courtyard.common.client import HubClient, HubError

PORT = 3635
HUB = f"http://127.0.0.1:{PORT}"
DB_NAME = "courtyard_teams_rb"
PG_PORT = os.environ.get("COURTYARD_PG_PORT", "26432")
PG_CONTAINER = os.environ.get("COURTYARD_COMPOSE_PROJECT", "courtyard") + "-postgres"
DB = f"postgresql://courtyard:courtyard@127.0.0.1:{PG_PORT}/{DB_NAME}"
FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "team-charter"


def hr(title):
    print("\n" + "=" * 78 + f"\n{title}\n" + "=" * 78)


def _read_yaml(path):
    return yaml.safe_load(path.read_text())


def psql(*statements, db="postgres"):
    subprocess.run(
        ["docker", "exec", PG_CONTAINER, "psql", "-U", "courtyard", "-d", db]
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
    hr("0. A CURRENT TEAM IS REQUIRED (D33 revised): registration refuses without one")
    try:
        admin.register_agent("too-early", "dummy")
        print("BUG: an agent registered with no team on the hub")
    except HubError as exc:
        print(f"refused           : {exc.code} — {exc}")

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

    hr("6. SELECTING A TEAM PROJECTS IT: CARDS -> REGISTRATIONS, LINKS -> LINES")
    # a private copy of the demo charter, so the workdir overlay never lands in the repo
    copy_dir = scratch / "demo-devops"
    shutil.copytree(FIXTURE, copy_dir)
    admin.remove_team(team.id)  # same directory content; the copy takes its place
    team = admin.add_team(str(copy_dir))
    admin.set_current_team(team.id)
    for agent in admin.agents():
        if agent.type != "human":
            print(f"registered        : {agent.name} ({agent.type}) — not for: {agent.anti_scope}")
    for line in admin.lines():
        print(f"line              : {line.agent_a_name} <-> {line.agent_b_name} [{line.mode}]")
    print(f"discovery         : {admin.settings()['discovery']} (declared by the charter)")
    projected = next(t for t in admin.teams() if t.id == team.id)
    print(f"report            : {projected.load_report or 'clean'}")

    hr("7. ANSWERING A WORKDIR WRITES THE OVERLAY AND THE REGISTRATION")
    project_dir = scratch / "infra-project"
    project_dir.mkdir()
    admin.set_team_workdir(team.id, "infra", str(project_dir))
    infra = next(a for a in admin.agents() if a.name == "infra")
    print(f"registration      : infra.workdir = {infra.workdir}")
    print("workdirs.local.yml:")
    print((copy_dir / "workdirs.local.yml").read_text())

    hr("8. THE FILES ARE THE MASTER: RELOAD MIRRORS EDITS, REASSERTS DECLARED MODES")
    (copy_dir / "infra" / "description.md").write_text("Now runs GCP too.\n")
    declared = next(
        li for li in admin.lines() if {li.agent_a_name, li.agent_b_name} == {"infra", "tf-dev"}
    )
    admin.set_mode(declared.id, "supervised")  # the operator flips the declared auto_pass line
    team = admin.reload_team(team.id)
    infra = next(a for a in admin.agents() if a.name == "infra")
    print(f"description       : {infra.description!r} (from the edited file)")
    declared = next(li for li in admin.lines() if li.id == declared.id)
    print(f"declared mode     : back to [{declared.mode}] (the charter says auto_pass)")

    hr("9. WRITE-BACK: AGENT ADD/EDIT/REMOVE LAND ON THE CHARTER FILES")
    scout_dir = scratch / "scout-project"
    scout_dir.mkdir()
    admin.register_agent(
        "scout",
        "claude-code",
        description="finds prior art",
        sme_domain="the research index",
        anti_scope="writing code",
        model="sonnet",
        color="teal",
        workdir=str(scout_dir),
    )
    print("registered scout  : the files followed —")
    print(
        "  the index entry :",
        _read_yaml(copy_dir / "team-definition.yml")["team"]["agents"]["scout"],
    )
    print("  scout/card.yml  :", _read_yaml(copy_dir / "scout" / "card.yml"))
    print("  description.md  :", (copy_dir / "scout" / "description.md").read_text().strip())
    print("  overlay workdir :", _read_yaml(copy_dir / "workdirs.local.yml")["workdirs"]["scout"])
    admin._call("PATCH", "/api/agents/scout", {"anti_scope": None, "model": "opus"})
    print(
        "after an edit     : card.yml model =", _read_yaml(copy_dir / "scout" / "card.yml")["model"]
    )
    print("cleared anti-scope: file exists =", (copy_dir / "scout" / "anti-scope.md").exists())
    admin.remove_agent("scout")
    print(
        "after remove      : yml agents =",
        list(_read_yaml(copy_dir / "team-definition.yml")["team"]["agents"]),
    )
    print("                    scout/ dir exists =", (copy_dir / "scout").exists())
    team = admin.reload_team(team.id)
    print(
        f"reload agrees     : report {team.load_report or 'clean'}, "
        f"agents {[a.name for a in team.charter.agents]}"
    )

    hr("10. THE SHIFT GUARD: NO RELOAD OF THE CURRENT TEAM MID-SHIFT")
    admin._call("POST", "/api/shift/start")
    try:
        admin.reload_team(team.id)
        print("BUG: reload went through during a shift")
    except HubError as exc:
        print(f"refused           : {exc.code} — {exc}")
    admin._call("POST", "/api/shift/end", {"force": True})
    print(f"after end shift   : reload OK ({admin.reload_team(team.id).name})")

    hr("11. CURRENT TEAM: ALWAYS EXACTLY ONE — NEVER CLEARED, NEVER REMOVED")
    teams = admin.set_current_team(team.id)
    print(f"current flags     : { {t.name: t.is_current for t in teams} }")
    try:
        admin.set_current_team(None)
        print("BUG: the selection cleared")
    except HubError as exc:
        print(f"clear refused     : {exc.code} — {exc}")
    try:
        admin.remove_team(team.id)
        print("BUG: the current team was removed")
    except HubError as exc:
        print(f"remove refused    : {exc.code} — {exc}")
    admin.remove_team(fresh.id)  # a non-current team goes; its files stay
    print(f"after remove      : {[t.name for t in admin.teams()]} registered")
    print(f"files stayed      : {(empty / 'team-definition.yml').is_file()}")
finally:
    admin.close()
    hub.terminate()
    hub.wait()
    psql(f"DROP DATABASE IF EXISTS {DB_NAME} WITH (FORCE)")
    print("\n(throwaway hub stopped, scratch database dropped; scratch dir left in /tmp.)")
