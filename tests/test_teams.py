"""The team charter registry (design team-charter.md, D33): loader units against the
committed fixture charter in tests/team-charter/, the API round trip (add, reload,
current selection, remove), slice 2 — projection of the current team's charter into
registrations and lines, the per-machine workdir overlay, and the shift guard — and
slice 3, write-back: agent add/edit/remove landing on the charter files; and the
agents' courtyard files written by the load that registers them."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import yaml

from courtyard.hub.core.charter import load_charter

FIXTURE = Path(__file__).parent / "team-charter"


def fixture_copy(tmp_path: Path) -> Path:
    """A private copy of the fixture charter, for tests that edit the files."""
    return shutil.copytree(FIXTURE, tmp_path / "team-charter")


# ---- the loader, straight against the fixture files --------------------------------


def test_fixture_charter_loads_clean():
    charter, report = load_charter(FIXTURE)
    assert report == []
    assert charter.name == "demo-devops"
    assert [a.name for a in charter.agents] == ["infra", "tf-dev", "scribe"]
    infra = charter.agents[0]
    assert (infra.type, infra.model, infra.color) == ("claude-code", "sonnet", "blue")
    assert "cloud" in infra.description
    assert infra.sme_domain.startswith("The AWS estate")
    assert "tf-dev writes them" in infra.anti_scope
    # gaps are allowed, not reported: tf-dev has no model or anti-scope, scribe only prose.
    # These also trip if a test ever write-backs into the committed fixture (slice 3):
    # tests that make a team current and touch agents must use fixture_copy.
    assert charter.agents[1].model is None
    assert charter.agents[2].type == "pi"
    assert charter.agents[2].sme_domain is None
    assert charter.agents[2].anti_scope is None
    # the declared topology (slice 2): two links, one with a mode, scribe-tf-dev none
    assert [(li.a, li.b, li.mode) for li in charter.links] == [
        ("infra", "tf-dev", "auto_pass"),
        ("infra", "scribe", None),
    ]
    # and the regime that makes the links the permission (D22)
    assert charter.discovery == "manual"


def test_example_charter_loads_clean():
    """The shipped example (examples/team-charters/aws-devops) must stay loadable —
    it is the worked example the docs point at."""
    example = Path(__file__).parents[1] / "examples" / "team-charters" / "aws-devops"
    charter, report = load_charter(example)
    assert report == []
    assert charter.name == "aws-devops"
    assert charter.discovery == "manual"
    assert {a.name for a in charter.agents} == {"infra-agent", "tf-developer", "argocd-agent"}
    assert all(a.type and a.description and a.sme_domain and a.anti_scope for a in charter.agents)
    assert [(li.a, li.b, li.mode) for li in charter.links] == [
        ("infra-agent", "tf-developer", "auto_pass"),
        ("infra-agent", "argocd-agent", None),
    ]


def test_missing_index_is_the_only_fatal_case(tmp_path):
    charter, report = load_charter(tmp_path)
    assert charter is None
    assert "no team-definition.yml" in report[0]


def test_broken_yaml_and_missing_root_are_reported(tmp_path):
    (tmp_path / "team-definition.yml").write_text("team: [unclosed")
    charter, report = load_charter(tmp_path)
    assert charter is None and "not valid YAML" in report[0]
    (tmp_path / "team-definition.yml").write_text("teams:\n  x:\n    agents: {}\n")
    charter, report = load_charter(tmp_path)
    assert charter is None and "`team:` mapping" in report[0]
    (tmp_path / "team-definition.yml").write_text("team:\n  agents: {}\n")
    charter, report = load_charter(tmp_path)
    assert charter is None and "team.name" in report[0]


def test_agent_problems_are_reported_not_fatal(tmp_path):
    (tmp_path / "team-definition.yml").write_text(
        "team:\n"
        "  name: broken-bits\n"
        "  agents:\n"
        "    ok-agent:\n"
        "      agent-config-dir: ok-agent\n"
        "    no-dir:\n"
        "      agent-config-dir: missing\n"
        "    escapee:\n"
        "      agent-config-dir: ../outside\n"
        "    'bad name!':\n"
        "      agent-config-dir: x\n"
    )
    ok = tmp_path / "ok-agent"
    ok.mkdir()
    (ok / "card.yml").write_text("type: rover\ncolor: mauve\nextra: field\n")
    charter, report = load_charter(tmp_path)
    assert charter.name == "broken-bits"
    # the valid names survive with what could be read; the invalid name is dropped
    assert [a.name for a in charter.agents] == ["ok-agent", "no-dir", "escapee"]
    assert charter.agents[0].type is None  # `rover` refused, reported
    joined = "\n".join(report)
    assert "type 'rover'" in joined and "color 'mauve'" in joined and "'extra'" in joined
    assert "does not exist" in joined
    assert "outside the charter directory" in joined
    assert "'bad name!'" in joined


# ---- the API round trip -------------------------------------------------------------


def test_add_list_reload_current_remove(bare_client, tmp_path):
    client = bare_client
    created = client.post("/api/teams", json={"charter_dir": str(FIXTURE)})
    assert created.status_code == 201, created.text
    team = created.json()
    assert team["name"] == "demo-devops" and team["load_report"] == []
    assert len(team["charter"]["agents"]) == 3
    assert not team["is_current"]

    # the same directory cannot be registered twice
    dup = client.post("/api/teams", json={"charter_dir": str(FIXTURE)})
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "team_exists"

    # a second team from an empty dir: name required, then bootstrapped and loadable
    empty = tmp_path / "new-team"
    empty.mkdir()
    unnamed = client.post("/api/teams", json={"charter_dir": str(empty)})
    assert unnamed.status_code == 422
    assert unnamed.json()["error"]["code"] == "charter_name_required"
    made = client.post("/api/teams", json={"charter_dir": str(empty), "name": "fresh"})
    assert made.status_code == 201, made.text
    assert made.json()["name"] == "fresh" and made.json()["charter"]["agents"] == []
    assert (empty / "team-definition.yml").is_file()

    # current: select, exactly one flagged; the selection moves, it never clears (D33)
    current = client.post("/api/teams/current", json={"team_id": team["id"]})
    flags = {t["id"]: t["is_current"] for t in current.json()}
    assert flags == {team["id"]: True, made.json()["id"]: False}
    cleared = client.post("/api/teams/current", json={"team_id": None})
    assert cleared.status_code == 409
    assert cleared.json()["error"]["code"] == "no_team"

    # the current team cannot be removed; any other can — the files stay either way
    stuck = client.delete(f"/api/teams/{team['id']}")
    assert stuck.status_code == 409 and stuck.json()["error"]["code"] == "no_team"
    gone = client.delete(f"/api/teams/{made.json()['id']}")
    assert gone.status_code == 200
    assert [t["id"] for t in client.get("/api/teams").json()] == [team["id"]]
    assert (empty / "team-definition.yml").is_file()


def test_reload_picks_up_edits_and_reports_breakage(bare_client, tmp_path):
    client = bare_client
    charter_dir = tmp_path / "reloadable"
    charter_dir.mkdir()
    made = client.post("/api/teams", json={"charter_dir": str(charter_dir), "name": "before"})
    team_id = made.json()["id"]

    # the hub never watches the filesystem: an edit lands only at reload
    (charter_dir / "team-definition.yml").write_text("team:\n  name: after\n  agents: {}\n")
    assert client.get("/api/teams").json()[0]["name"] == "before"
    reloaded = client.post(f"/api/teams/{team_id}/reload")
    assert reloaded.json()["name"] == "after"
    assert reloaded.json()["loaded_at"] > made.json()["loaded_at"]

    # a broken charter keeps the row (and last name) but shows the report, no charter
    (charter_dir / "team-definition.yml").write_text("nonsense: [")
    broken = client.post(f"/api/teams/{team_id}/reload").json()
    assert broken["charter"] is None and broken["name"] == "after"
    assert "not valid YAML" in broken["load_report"][0]


def test_add_refuses_a_missing_directory(client, tmp_path):
    missing = client.post("/api/teams", json={"charter_dir": str(tmp_path / "nope")})
    assert missing.status_code == 400
    assert missing.json()["error"]["code"] == "workdir_not_found"


def test_nonempty_dir_gets_the_initialize_offer(client, tmp_path):
    """Item 43 follow-up: a directory without team-definition.yml is not refused; the
    422 is the UI's cue to offer initialization, and the name confirms it. Existing
    files are untouched — the hub only adds the index."""
    populated = tmp_path / "project"
    populated.mkdir()
    (populated / "somefile.txt").write_text("hi")
    offer = client.post("/api/teams", json={"charter_dir": str(populated)})
    assert offer.status_code == 422
    assert offer.json()["error"]["code"] == "charter_name_required"
    assert not (populated / "team-definition.yml").exists()  # nothing written yet
    made = client.post("/api/teams", json={"charter_dir": str(populated), "name": "adopted"})
    assert made.status_code == 201, made.text
    assert made.json()["name"] == "adopted"
    assert (populated / "team-definition.yml").is_file()
    assert (populated / "somefile.txt").read_text() == "hi"


def test_link_problems_are_reported_not_fatal(tmp_path):
    charter_dir = fixture_copy(tmp_path)
    (charter_dir / "team-definition.yml").write_text(
        "team:\n"
        "  name: demo-devops\n"
        "  agents:\n"
        "    infra:\n"
        "      agent-config-dir: infra\n"
        "    tf-dev:\n"
        "      agent-config-dir: tf-dev\n"
        "  links:\n"
        "    - between: [infra, tf-dev]\n"
        "      mode: gated   # not a mode\n"
        "    - between: [infra, stranger]\n"
        "    - between: [infra, infra]\n"
        "    - between: [infra]\n"
        "    - just a string\n"
    )
    charter, report = load_charter(charter_dir)
    # the good pair survives, its bad mode dropped and reported; the rest are dropped
    assert [(li.a, li.b, li.mode) for li in charter.links] == [("infra", "tf-dev", None)]
    joined = "\n".join(report)
    assert "'gated'" in joined
    assert "stranger" in joined
    assert "to itself" in joined
    assert "exactly two agent names" in joined


def test_bad_discovery_is_reported_and_left_undeclared(tmp_path):
    (tmp_path / "team-definition.yml").write_text(
        "team:\n  name: t\n  discovery: open\n  agents: {}\n"
    )
    charter, report = load_charter(tmp_path)
    assert charter.discovery is None
    assert "`team.discovery` must be auto or manual" in report[0]


def test_workdir_overlay_fills_cards_and_reports_strangers(tmp_path):
    charter_dir = fixture_copy(tmp_path)
    (charter_dir / "workdirs.local.yml").write_text(
        f"workdirs:\n  infra: {tmp_path}\n  stranger: /nowhere\n"
    )
    charter, report = load_charter(charter_dir)
    assert charter.agents[0].workdir == str(tmp_path)
    assert charter.agents[1].workdir is None
    assert "stranger" in report[0]


def test_add_with_broken_charter_registers_and_reports(client, tmp_path):
    """A directory WITH a charter file always registers; problems go to the report —
    the WebUI's job is to display them (design team-charter.md §3)."""
    charter_dir = tmp_path / "broken"
    charter_dir.mkdir()
    (charter_dir / "team-definition.yml").write_text("team:\n  agents: {}\n")
    made = client.post("/api/teams", json={"charter_dir": str(charter_dir)})
    assert made.status_code == 201, made.text
    body = made.json()
    assert body["name"] is None and body["charter"] is None
    assert "team.name" in body["load_report"][0]


# ---- slice 2: projection into registrations and lines -------------------------------


def _make_current(client, charter_dir) -> str:
    made = client.post("/api/teams", json={"charter_dir": str(charter_dir)})
    assert made.status_code == 201, made.text
    team_id = made.json()["id"]
    current = client.post("/api/teams/current", json={"team_id": team_id})
    assert current.status_code == 200, current.text
    return team_id


def _agents_by_name(client) -> dict:
    return {a["name"]: a for a in client.get("/api/agents").json()}


def _lines_by_pair(client) -> dict:
    return {
        frozenset((li["agent_a_name"], li["agent_b_name"])): li
        for li in client.get("/api/lines").json()
    }


def test_selecting_a_team_projects_cards_and_links(bare_client):
    """Becoming current is the initialization gesture: cards become registrations,
    links become lines with their declared modes (design team-charter.md §6)."""
    client = bare_client
    team_id = _make_current(client, FIXTURE)
    agents = _agents_by_name(client)
    assert {"operator", "infra", "tf-dev", "scribe"} <= set(agents)
    infra = agents["infra"]
    assert infra["type"] == "claude-code" and infra["model"] == "sonnet"
    assert infra["color"] == "blue" and infra["sme_domain"].startswith("The AWS estate")
    assert "tf-dev writes them" in infra["anti_scope"]
    assert agents["scribe"]["type"] == "pi"
    lines = _lines_by_pair(client)
    assert set(lines) == {frozenset(("infra", "tf-dev")), frozenset(("infra", "scribe"))}
    assert lines[frozenset(("infra", "tf-dev"))]["mode"] == "auto_pass"
    assert lines[frozenset(("infra", "scribe"))]["mode"] == "supervised"  # the default
    # the declared discovery regime landed on the Settings dial
    assert client.get("/api/settings").json()["discovery"] == "manual"
    # projection found nothing to complain about, and reloading is idempotent
    assert client.get("/api/teams").json()[0]["load_report"] == []
    reloaded = client.post(f"/api/teams/{team_id}/reload")
    assert reloaded.json()["load_report"] == []
    assert len(client.get("/api/agents").json()) == 4


def test_reload_mirrors_the_files_and_reasserts_declared_modes(client, tmp_path):
    charter_dir = fixture_copy(tmp_path)
    team_id = _make_current(client, charter_dir)
    # the files are the master: edits land on the registration, a removed file clears
    (charter_dir / "infra" / "description.md").write_text("Now runs GCP too.\n")
    (charter_dir / "infra" / "anti-scope.md").unlink()
    lines = _lines_by_pair(client)
    declared = lines[frozenset(("infra", "tf-dev"))]  # auto_pass in the charter
    undeclared = lines[frozenset(("infra", "scribe"))]  # no mode in the charter
    client.post(f"/api/lines/{declared['id']}/mode", json={"mode": "supervised"})
    client.post(f"/api/lines/{undeclared['id']}/mode", json={"mode": "auto_pass"})
    assert client.post(f"/api/teams/{team_id}/reload").status_code == 200
    infra = _agents_by_name(client)["infra"]
    assert infra["description"] == "Now runs GCP too."
    assert infra["anti_scope"] is None
    lines = _lines_by_pair(client)
    # a declared mode is reasserted; an undeclared line keeps the operator's dial
    assert lines[frozenset(("infra", "tf-dev"))]["mode"] == "auto_pass"
    assert lines[frozenset(("infra", "scribe"))]["mode"] == "auto_pass"
    # declared discovery is reasserted over an Admin flip the same way
    client.patch("/api/settings", json={"discovery": "auto"})
    assert client.post(f"/api/teams/{team_id}/reload").status_code == 200
    assert client.get("/api/settings").json()["discovery"] == "manual"


def test_projection_is_additive_and_reports_name_conflicts(client, make_agent, tmp_path):
    """Projection never removes anything, and the courtyard's permanent identities
    (types, the operator) win over what a charter claims. A removed name is not one of
    them any more: a charter that names it gets it registered again (the files are the
    master), on the row the old life left behind."""
    make_agent("outsider")  # registered by hand, not in the charter
    make_agent("infra", type="dummy", description="was here first")
    removed, _ = make_agent("old-timer")
    client.delete("/api/agents/old-timer")
    charter_dir = tmp_path / "clashing"
    for sub in ("infra", "old-timer", "operator", "typeless"):
        (charter_dir / sub).mkdir(parents=True)
    (charter_dir / "infra" / "description.md").write_text("the charter's words\n")
    (charter_dir / "infra" / "card.yml").write_text("type: claude-code\n")
    (charter_dir / "old-timer" / "card.yml").write_text("type: claude-code\n")
    (charter_dir / "old-timer" / "description.md").write_text("back on the team\n")
    (charter_dir / "team-definition.yml").write_text(
        "team:\n"
        "  name: clashing\n"
        "  agents:\n"
        "    infra:\n"
        "      agent-config-dir: infra\n"
        "    old-timer:\n"
        "      agent-config-dir: old-timer\n"
        "    operator:\n"
        "      agent-config-dir: operator\n"
        "    typeless:\n"
        "      agent-config-dir: typeless\n"
        "  links:\n"
        "    - between: [infra, typeless]\n"
    )
    team_id = _make_current(client, charter_dir)
    report = "\n".join(
        next(t for t in client.get("/api/teams").json() if t["id"] == team_id)["load_report"]
    )
    assert "the type is a permanent identity and stays dummy" in report
    assert "old-timer" not in report  # revived, not reported
    assert "on the roster by design" in report
    assert "declares no type; not registered" in report
    agents = _agents_by_name(client)
    assert "outsider" in agents and "typeless" not in agents
    revived = agents["old-timer"]
    assert revived["id"] == removed["id"] and revived["removed_at"] is None
    assert revived["type"] == "claude-code" and revived["description"] == "back on the team"
    assert agents["infra"]["type"] == "dummy"  # kept
    # this charter declares no discovery, so the dial stays the operator's (auto)
    assert client.get("/api/settings").json()["discovery"] == "auto"
    assert agents["infra"]["description"] == "the charter's words"  # prose still mirrored
    assert client.get("/api/lines").json() == []  # half a link helps nobody


def test_workdir_answer_writes_the_overlay_and_the_registration(client, tmp_path):
    charter_dir = fixture_copy(tmp_path)
    team_id = _make_current(client, charter_dir)
    project = tmp_path / "infra-project"
    project.mkdir()
    answered = client.post(
        f"/api/teams/{team_id}/workdirs", json={"agent": "infra", "workdir": str(project)}
    )
    assert answered.status_code == 200, answered.text
    overlay = (charter_dir / "workdirs.local.yml").read_text()
    assert "Never commit" in overlay and str(project) in overlay
    assert _agents_by_name(client)["infra"]["workdir"] == str(project)
    # a second answer keeps the first entry
    other = tmp_path / "scribe-project"
    other.mkdir()
    client.post(f"/api/teams/{team_id}/workdirs", json={"agent": "scribe", "workdir": str(other)})
    overlay = (charter_dir / "workdirs.local.yml").read_text()
    assert str(project) in overlay and str(other) in overlay
    # refusals: not a charter agent; not a directory
    stranger = client.post(
        f"/api/teams/{team_id}/workdirs", json={"agent": "stranger", "workdir": str(project)}
    )
    assert stranger.status_code == 404
    nowhere = client.post(
        f"/api/teams/{team_id}/workdirs", json={"agent": "infra", "workdir": str(project / "no")}
    )
    assert nowhere.status_code == 400


def test_shift_guard_refuses_projection_while_a_shift_runs(client):
    """D33's lean guard: projection changes registrations under live agents, so the
    current team can be neither reloaded nor changed until the shift ends."""
    team_id = _make_current(client, FIXTURE)
    assert client.post("/api/shift/start").status_code == 200
    refused = client.post(f"/api/teams/{team_id}/reload")
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "shift_active"
    reselect = client.post("/api/teams/current", json={"team_id": team_id})
    assert reselect.status_code == 409
    assert reselect.json()["error"]["code"] == "shift_active"
    # the selection never clears (D33 revised), whatever the shift state
    refusedclear = client.post("/api/teams/current", json={"team_id": None})
    assert refusedclear.status_code == 409
    assert refusedclear.json()["error"]["code"] == "no_team"
    client.post("/api/shift/end", json={"force": True})
    assert client.post("/api/teams/current", json={"team_id": team_id}).status_code == 200


def test_anti_scope_reaches_the_peers_roster(client, tmp_path):
    """One "not for:" line per peer (D33), collapsed to a single line however the
    anti-scope.md file was wrapped."""
    from conftest import auth

    # a COPY: the patch below write-backs into the charter files (slice 3), and the
    # committed fixture must never be edited by the suite
    _make_current(client, fixture_copy(tmp_path))
    token = client.get("/api/agents/tf-dev/token").json()["token"]
    view = client.get("/api/agents/tf-dev/peers", headers=auth(token))
    assert view.status_code == 200, view.text
    rendered = view.json()["rendered"]
    assert (
        "not for: application code or Terraform module internals; "
        "it consumes modules, tf-dev writes them" in rendered
    )
    # editable on the agent form too, like the other prose fields
    patched = client.patch("/api/agents/scribe", json={"anti_scope": "code of any kind"})
    assert patched.json()["anti_scope"] == "code of any kind"


# ---- slice 3: write-back from the agent forms ---------------------------------------


def _read_yaml(path: Path):
    return yaml.safe_load(path.read_text())


def test_adding_an_agent_writes_it_into_the_charter(client, tmp_path):
    """With a current team, a registration also lands in the files: yml entry, config
    dir, card.yml, prose files, and the workdir in the per-machine overlay."""
    charter_dir = fixture_copy(tmp_path)
    _make_current(client, charter_dir)
    project = tmp_path / "scout-project"
    project.mkdir()
    created = client.post(
        "/api/agents",
        json={
            "name": "scout",
            "type": "claude-code",
            "description": "finds prior art",
            "sme_domain": "the research index",
            "anti_scope": "writing code",
            "model": "sonnet",
            "color": "teal",
            "workdir": str(project),
        },
    )
    assert created.status_code == 201, created.text
    index = _read_yaml(charter_dir / "team-definition.yml")
    assert index["team"]["agents"]["scout"] == {"agent-config-dir": "scout"}
    card = _read_yaml(charter_dir / "scout" / "card.yml")
    assert card == {"type": "claude-code", "model": "sonnet", "color": "teal"}
    assert (charter_dir / "scout" / "description.md").read_text() == "finds prior art\n"
    assert (charter_dir / "scout" / "owns.md").read_text() == "the research index\n"
    assert (charter_dir / "scout" / "anti-scope.md").read_text() == "writing code\n"
    assert _read_yaml(charter_dir / "workdirs.local.yml")["workdirs"]["scout"] == str(project)
    # the rewrite kept what the index already had
    assert set(index["team"]["agents"]) == {"infra", "tf-dev", "scribe", "scout"}
    assert index["team"]["discovery"] == "manual" and len(index["team"]["links"]) == 2
    # the hub's cached charter follows the files it just wrote, without a manual reload
    team = next(t for t in client.get("/api/teams").json() if t["is_current"])
    assert "scout" in [a["name"] for a in team["charter"]["agents"]]
    assert team["load_report"] == []
    # and a reload finds nothing to disagree with: write-back round-trips exactly
    before = _agents_by_name(client)["scout"]
    assert client.post(f"/api/teams/{team['id']}/reload").json()["load_report"] == []
    assert _agents_by_name(client)["scout"] == before


def test_hub_picked_color_stays_undeclared_in_the_card(client, tmp_path):
    """A colour the request did not declare is the hub's nicety, not charter content —
    card.yml stays without one, matching how projection treats an undeclared colour."""
    charter_dir = fixture_copy(tmp_path)
    _make_current(client, charter_dir)
    made = client.post("/api/agents", json={"name": "quiet", "type": "dummy"})
    assert made.status_code == 201, made.text
    assert made.json()["agent"]["color"] is not None  # the hub picked one
    assert _read_yaml(charter_dir / "quiet" / "card.yml") == {"type": "dummy"}
    # no prose was given, so no prose files exist
    assert sorted(p.name for p in (charter_dir / "quiet").iterdir()) == ["card.yml"]


def test_write_back_is_bound_to_the_current_team_only(client, tmp_path):
    """A registered but not current team is display only: agent changes land on the
    CURRENT team's files and nowhere else."""
    charter_dir = fixture_copy(tmp_path)
    made = client.post("/api/teams", json={"charter_dir": str(charter_dir)})
    assert made.status_code == 201
    index_before = (charter_dir / "team-definition.yml").read_text()
    assert client.post("/api/agents", json={"name": "solo", "type": "dummy"}).status_code == 201
    assert (client.team_dir / "solo" / "card.yml").exists()  # the current team's files
    assert client.patch("/api/agents/solo", json={"description": "db only"}).status_code == 200
    assert client.delete("/api/agents/solo").status_code == 200
    assert not (client.team_dir / "solo").exists()
    assert (charter_dir / "team-definition.yml").read_text() == index_before
    assert not (charter_dir / "solo").exists()


def test_editing_a_charter_agent_writes_the_card_files(client, tmp_path):
    charter_dir = fixture_copy(tmp_path)
    _make_current(client, charter_dir)
    patched = client.patch(
        "/api/agents/infra",
        json={"description": "Runs GCP now.", "anti_scope": None, "model": "opus"},
    )
    assert patched.status_code == 200, patched.text
    assert (charter_dir / "infra" / "description.md").read_text() == "Runs GCP now.\n"
    assert not (charter_dir / "infra" / "anti-scope.md").exists()  # cleared = file gone
    card = _read_yaml(charter_dir / "infra" / "card.yml")
    assert card["model"] == "opus" and card["type"] == "claude-code"  # untouched keys stay
    assert (charter_dir / "infra" / "owns.md").exists()  # unpatched prose untouched
    # a patched workdir goes to the overlay, and clearing it drops the entry
    project = tmp_path / "infra-project"
    project.mkdir()
    client.patch("/api/agents/infra", json={"workdir": str(project)})
    assert _read_yaml(charter_dir / "workdirs.local.yml")["workdirs"] == {"infra": str(project)}
    client.patch("/api/agents/infra", json={"workdir": None})
    assert _read_yaml(charter_dir / "workdirs.local.yml")["workdirs"] == {}
    # the cached charter followed along; a reload agrees with the database
    team = next(t for t in client.get("/api/teams").json() if t["is_current"])
    assert team["load_report"] == []
    assert client.post(f"/api/teams/{team['id']}/reload").json()["load_report"] == []
    infra = _agents_by_name(client)["infra"]
    assert infra["description"] == "Runs GCP now." and infra["anti_scope"] is None


def test_editing_an_agent_outside_the_charter_stays_db_only(client, make_agent, tmp_path):
    """An agent of another registered team keeps the database as its edit surface;
    the current charter never learns about it (design team-charter.md §3)."""
    make_agent("veteran")
    charter_dir = fixture_copy(tmp_path)
    _make_current(client, charter_dir)
    index_before = (charter_dir / "team-definition.yml").read_text()
    assert client.patch("/api/agents/veteran", json={"description": "still db"}).status_code == 200
    assert client.delete("/api/agents/veteran").status_code == 200
    assert (charter_dir / "team-definition.yml").read_text() == index_before
    assert not (charter_dir / "veteran").exists()


def test_removing_a_charter_agent_leaves_the_files_too(client, tmp_path):
    """Removal write-back: the yml entry, the links naming the agent, the overlay entry
    and the configuration directory all go — a reload cannot resurrect the agent."""
    charter_dir = fixture_copy(tmp_path)
    team_id = _make_current(client, charter_dir)
    project = tmp_path / "infra-project"
    project.mkdir()
    client.post(f"/api/teams/{team_id}/workdirs", json={"agent": "infra", "workdir": str(project)})
    removed = client.delete("/api/agents/infra")
    assert removed.status_code == 200, removed.text
    team = _read_yaml(charter_dir / "team-definition.yml")["team"]
    assert set(team["agents"]) == {"tf-dev", "scribe"}
    assert "links" not in team  # both fixture links named infra
    assert not (charter_dir / "infra").exists()
    assert (charter_dir / "tf-dev" / "card.yml").exists()  # the others untouched
    assert _read_yaml(charter_dir / "workdirs.local.yml")["workdirs"] == {}
    # the cached charter followed, and a reload reports nothing: no resurrection
    reloaded = client.post(f"/api/teams/{team_id}/reload").json()
    assert reloaded["load_report"] == []
    assert [a["name"] for a in reloaded["charter"]["agents"]] == ["tf-dev", "scribe"]
    assert _agents_by_name(client)["infra"]["removed_at"] is not None


def test_agent_changes_refuse_while_the_current_charter_is_broken(client, tmp_path):
    """A current team whose charter did not load cannot be written back into, so the
    change refuses BEFORE the database is touched — no divergence to reconcile."""
    charter_dir = fixture_copy(tmp_path)
    team_id = _make_current(client, charter_dir)
    (charter_dir / "team-definition.yml").write_text("team: [broken")
    assert client.post(f"/api/teams/{team_id}/reload").status_code == 200  # report, no charter
    refused = client.post("/api/agents", json={"name": "late", "type": "dummy"})
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "charter_not_loaded"
    assert "late" not in _agents_by_name(client)  # the database was never touched
    assert client.patch("/api/agents/infra", json={"model": "opus"}).status_code == 409
    assert client.delete("/api/agents/infra").status_code == 409
    # recovery: the selection moves to a healthy team (it can never be cleared)
    assert client.post("/api/teams/current", json={"team_id": None}).status_code == 409
    healthy = next(t for t in client.get("/api/teams").json() if t["name"] == "test-team")
    assert client.post("/api/teams/current", json={"team_id": healthy["id"]}).status_code == 200
    assert client.post("/api/agents", json={"name": "late", "type": "dummy"}).status_code == 201


def test_write_failure_reports_the_half_state(client, tmp_path):
    """When the files cannot be written after the database was, the error says exactly
    what state that leaves. Rare (the dir was writable at load time), so honesty over
    rollback machinery."""
    charter_dir = fixture_copy(tmp_path)
    _make_current(client, charter_dir)
    charter_dir.chmod(0o555)  # the hub can read the charter but not write it
    try:
        failed = client.post("/api/agents", json={"name": "walled", "type": "dummy"})
        assert failed.status_code == 409, failed.text
        assert failed.json()["error"]["code"] == "charter_write_failed"
        assert "registered on the hub" in failed.json()["error"]["message"]
        assert "walled" in _agents_by_name(client)  # the half-state the message names
    finally:
        charter_dir.chmod(0o755)


def test_config_dir_name_avoids_clashes(client, tmp_path):
    """The new agent's directory is named after it; a name already used by another
    entry's directory (or a plain file) gets a numbered suffix instead."""
    charter_dir = fixture_copy(tmp_path)
    (charter_dir / "blocked").write_text("a file where the dir would go")
    index = _read_yaml(charter_dir / "team-definition.yml")
    index["team"]["agents"]["oddly"] = {"agent-config-dir": "taken"}
    (charter_dir / "taken").mkdir()
    (charter_dir / "taken" / "card.yml").write_text("type: dummy\n")
    (charter_dir / "team-definition.yml").write_text(yaml.safe_dump(index, sort_keys=False))
    _make_current(client, charter_dir)
    assert client.post("/api/agents", json={"name": "blocked", "type": "dummy"}).status_code == 201
    assert client.post("/api/agents", json={"name": "taken", "type": "dummy"}).status_code == 201
    agents = _read_yaml(charter_dir / "team-definition.yml")["team"]["agents"]
    assert agents["blocked"] == {"agent-config-dir": "blocked-2"}
    assert agents["taken"] == {"agent-config-dir": "taken-2"}
    assert _read_yaml(charter_dir / "taken" / "card.yml") == {"type": "dummy"}  # untouched


# ---- D33 revised: a current team is required ----------------------------------------


def test_registration_is_refused_before_a_team_exists(bare_client):
    """The charter is the source of truth, so it needs a home before the first agent:
    the transient pre-team state accepts team registration and nothing else."""
    refused = bare_client.post("/api/agents", json={"name": "early", "type": "dummy"})
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "no_team"
    assert "charter directory" in refused.json()["error"]["message"]
    assert [a["name"] for a in bare_client.get("/api/agents").json()] == ["operator"]


def test_choosing_a_team_adopts_agents_no_charter_names(client, make_agent, tmp_path):
    """An orphan (its charter entry hand-deleted, then reloaded: projection is
    additive) is written into the next team made current. The operator and removed
    names are never adopted."""
    make_agent("pioneer")
    make_agent("goner")
    client.delete("/api/agents/goner")  # removed: the name is burned, never adopted
    # hand-edit the current team's files: pioneer leaves the charter, stays registered
    index = _read_yaml(client.team_dir / "team-definition.yml")
    del index["team"]["agents"]["pioneer"]
    (client.team_dir / "team-definition.yml").write_text(yaml.safe_dump(index, sort_keys=False))
    test_team = next(t for t in client.get("/api/teams").json() if t["name"] == "test-team")
    assert client.post(f"/api/teams/{test_team['id']}/reload").status_code == 200
    assert "pioneer" in _agents_by_name(client)  # projection is additive: still registered

    charter_dir = fixture_copy(tmp_path)
    _make_current(client, charter_dir)

    adopted = _read_yaml(charter_dir / "team-definition.yml")["team"]["agents"]
    assert "pioneer" in adopted
    assert "goner" not in adopted and "operator" not in adopted
    assert _read_yaml(charter_dir / "pioneer" / "card.yml") == {"type": "dummy"}
    # adopted means owned: edits now land on THIS charter's files
    client.patch("/api/agents/pioneer", json={"description": "adopted"})
    assert (charter_dir / "pioneer" / "description.md").read_text() == "adopted\n"


# ---- the load writes the agents' files (team-charter.md §6, D33) --------------------


def _with_workdirs(charter_dir: Path, workdirs: dict[str, Path]) -> None:
    (charter_dir / "workdirs.local.yml").write_text(
        yaml.safe_dump({"workdirs": {name: str(path) for name, path in workdirs.items()}})
    )


def _project_dir(tmp_path: Path, name: str) -> Path:
    path = tmp_path / f"{name}-project"
    path.mkdir()
    return path


def _current_team(client) -> dict:
    return next(t for t in client.get("/api/teams").json() if t["is_current"])


def _token(client, name: str) -> str:
    return client.get(f"/api/agents/{name}/token").json()["token"]


def _courtyard_server(workdir: Path) -> dict:
    return json.loads((workdir / ".mcp.json").read_text())["mcpServers"]["courtyard"]


def test_loading_the_first_team_writes_each_new_agents_files(bare_client, tmp_path):
    """A fresh hub, a charter whose overlay knows the workdirs: choosing it registers the
    agents AND writes their files with the fresh tokens, so Start shift finds them."""
    client = bare_client
    charter_dir = fixture_copy(tmp_path)
    infra_dir, scribe_dir = _project_dir(tmp_path, "infra"), _project_dir(tmp_path, "scribe")
    _with_workdirs(charter_dir, {"infra": infra_dir, "scribe": scribe_dir})
    _make_current(client, charter_dir)

    assert _courtyard_server(infra_dir)["env"] == {
        "COURTYARD_HUB_URL": "http://testserver",
        "COURTYARD_AGENT_NAME": "infra",
        "COURTYARD_TOKEN": _token(client, "infra"),
    }
    assert (infra_dir / ".mcp.json").stat().st_mode & 0o777 == 0o600
    settings = json.loads((infra_dir / ".claude" / "settings.local.json").read_text())
    assert settings["model"] == "sonnet" and "SessionStart" in settings["hooks"]
    assert "--model sonnet" in (infra_dir / "start-with-courtyard.sh").read_text()
    # pi gets its own set, with its own token
    extension = (scribe_dir / ".pi" / "extensions" / "courtyard.ts").read_text()
    assert _token(client, "scribe") in extension
    assert (scribe_dir / ".pi" / "skills" / "courtyard" / "SKILL.md").is_file()

    team = _current_team(client)
    assert team["load_report"] == []
    files = "\n".join(team["files_report"])
    assert f"infra: courtyard files written into {infra_dir}. Written: .mcp.json" in files
    assert f"scribe: courtyard files written into {scribe_dir}" in files
    assert "tf-dev: no project directory on this machine yet" in files


def test_files_left_by_an_earlier_hub_get_the_new_token(bare_client, tmp_path):
    """The rebuilt-from-charter case: the workdir still holds a config with a dead token
    and an old adapter path. Our entry is replaced, other servers stay, the old file is
    kept as the backup."""
    client = bare_client
    charter_dir = fixture_copy(tmp_path)
    infra_dir = _project_dir(tmp_path, "infra")
    stale = {
        "mcpServers": {
            "courtyard": {"command": "/gone/.venv/bin/courtyard-claude-mcp", "env": {}},
            "other": {"command": "other-server"},
        }
    }
    (infra_dir / ".mcp.json").write_text(json.dumps(stale))
    _with_workdirs(charter_dir, {"infra": infra_dir})
    _make_current(client, charter_dir)
    servers = json.loads((infra_dir / ".mcp.json").read_text())["mcpServers"]
    assert servers["other"] == {"command": "other-server"}
    assert servers["courtyard"]["env"]["COURTYARD_TOKEN"] == _token(client, "infra")
    assert servers["courtyard"]["command"] != "/gone/.venv/bin/courtyard-claude-mcp"
    assert "/gone/.venv" in (infra_dir / ".mcp.json.courtyard-bak").read_text()


def test_reload_does_not_rewrite_registered_agents(bare_client, tmp_path):
    """Their token did not change, so a reload leaves their directories alone."""
    client = bare_client
    charter_dir = fixture_copy(tmp_path)
    infra_dir = _project_dir(tmp_path, "infra")
    _with_workdirs(charter_dir, {"infra": infra_dir})
    team_id = _make_current(client, charter_dir)
    (infra_dir / ".mcp.json").unlink()  # the operator took it out by hand
    reloaded = client.post(f"/api/teams/{team_id}/reload").json()
    assert not (infra_dir / ".mcp.json").exists()
    assert reloaded["files_report"] == [] and reloaded["load_report"] == []


def test_choosing_a_workdir_writes_that_agents_files(client, tmp_path):
    """The cloned-charter case: no overlay, so the load registers without files; the
    directory chosen in the Teams view gets the agent's files, exactly once."""
    charter_dir = fixture_copy(tmp_path)
    card = charter_dir / "tf-dev" / "card.yml"
    card.write_text("color: green\n")  # typeless: not registered by the first load
    team_id = _make_current(client, charter_dir)
    notes = "\n".join(_current_team(client)["files_report"])
    assert "infra: no project directory on this machine yet" in notes
    assert "tf-dev" not in _agents_by_name(client)

    # registered at the earlier load: its stored token goes into the chosen directory
    infra_dir = _project_dir(tmp_path, "infra")
    answered = client.post(
        f"/api/teams/{team_id}/workdirs", json={"agent": "infra", "workdir": str(infra_dir)}
    ).json()
    assert _courtyard_server(infra_dir)["env"]["COURTYARD_TOKEN"] == _token(client, "infra")
    assert len(answered["files_report"]) == 1
    assert answered["files_report"][0].startswith(
        f"infra: courtyard files written into {infra_dir}"
    )

    # registered by the answer's own reload (the card got its type back): written once
    card.write_text("type: claude-code\ncolor: green\n")
    tf_dir = _project_dir(tmp_path, "tf-dev")
    client.post(f"/api/teams/{team_id}/workdirs", json={"agent": "tf-dev", "workdir": str(tf_dir)})
    assert _courtyard_server(tf_dir)["env"]["COURTYARD_TOKEN"] == _token(client, "tf-dev")
    assert not (tf_dir / ".mcp.json.courtyard-bak").exists()


def test_file_problems_are_reported_per_agent_and_the_load_goes_on(bare_client, tmp_path):
    client = bare_client
    charter_dir = fixture_copy(tmp_path)
    infra_dir, scribe_dir = _project_dir(tmp_path, "infra"), _project_dir(tmp_path, "scribe")
    (infra_dir / ".mcp.json").write_text("{ not json")
    moved = tmp_path / "moved-away"
    _with_workdirs(charter_dir, {"infra": infra_dir, "tf-dev": moved, "scribe": scribe_dir})
    _make_current(client, charter_dir)
    report = "\n".join(_current_team(client)["load_report"])
    assert f"agent infra: its courtyard files were not written into {infra_dir}" in report
    assert "not valid JSON" in report
    assert f"agent tf-dev: its courtyard files were not written into {moved}" in report
    assert (infra_dir / ".mcp.json").read_text() == "{ not json"  # never overwritten blindly
    assert (scribe_dir / ".pi" / "extensions" / "courtyard.ts").is_file()  # the rest went on
    assert {"infra", "tf-dev", "scribe"} <= set(_agents_by_name(client))


def test_a_team_that_is_not_current_writes_no_files(client, tmp_path):
    charter_dir = fixture_copy(tmp_path)
    infra_dir, scribe_dir = _project_dir(tmp_path, "infra"), _project_dir(tmp_path, "scribe")
    _with_workdirs(charter_dir, {"infra": infra_dir})
    team_id = client.post("/api/teams", json={"charter_dir": str(charter_dir)}).json()["id"]
    assert client.post(f"/api/teams/{team_id}/reload").json()["files_report"] == []
    client.post(
        f"/api/teams/{team_id}/workdirs", json={"agent": "scribe", "workdir": str(scribe_dir)}
    )
    assert list(infra_dir.iterdir()) == [] and list(scribe_dir.iterdir()) == []
    assert "infra" not in _agents_by_name(client)


def test_a_revived_name_gets_files_with_its_new_token(client, make_agent, tmp_path):
    _, old_token = make_agent("infra")
    client.delete("/api/agents/infra")
    charter_dir = fixture_copy(tmp_path)
    infra_dir = _project_dir(tmp_path, "infra")
    _with_workdirs(charter_dir, {"infra": infra_dir})
    _make_current(client, charter_dir)
    written = _courtyard_server(infra_dir)["env"]["COURTYARD_TOKEN"]
    assert written == _token(client, "infra") and written != old_token
