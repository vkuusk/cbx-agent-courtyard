"""The team charter registry, slice 1 (design team-charter.md, D33): loader units
against the committed fixture charter in tests/team-charter/, and the API round trip
(add, reload, current selection, remove) against the real hub."""

from __future__ import annotations

from pathlib import Path

from courtyard.hub.core.charter import load_charter

FIXTURE = Path(__file__).parent / "team-charter"


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
    # gaps are allowed, not reported: tf-dev has no model or anti-scope, scribe only prose
    assert charter.agents[1].model is None
    assert charter.agents[2].type == "pi"
    assert charter.agents[2].sme_domain is None


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


def test_add_list_reload_current_remove(client, tmp_path):
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

    # current: select, exactly one flagged, then clear
    current = client.post("/api/teams/current", json={"team_id": team["id"]})
    flags = {t["id"]: t["is_current"] for t in current.json()}
    assert flags == {team["id"]: True, made.json()["id"]: False}
    cleared = client.post("/api/teams/current", json={"team_id": None})
    assert all(not t["is_current"] for t in cleared.json())

    # remove drops the registry row and only that — the files stay
    gone = client.delete(f"/api/teams/{made.json()['id']}")
    assert gone.status_code == 200
    assert [t["id"] for t in client.get("/api/teams").json()] == [team["id"]]
    assert (empty / "team-definition.yml").is_file()


def test_reload_picks_up_edits_and_reports_breakage(client, tmp_path):
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
