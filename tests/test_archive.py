"""Archiving line histories (design §5.7, D20): on request, on agent removal, at startup."""

import json

import psycopg
from fastapi.testclient import TestClient

from conftest import auth
from courtyard.hub.main import create_app


def converse(client, make_agent):
    """alice ↔ bob, three entries: alice's opening (approved with a note) and bob's reply."""
    _, alice = make_agent("alice")
    _, bob = make_agent("bob")
    m1 = client.post("/api/lines/send", json={"to": "bob", "body": "hi bob"}, headers=auth(alice))
    assert m1.status_code == 201, m1.text
    line_id = m1.json()["line_id"]
    client.post(f"/api/gate/{m1.json()['id']}", json={"verdict": "approve", "note": "go"})
    m2 = client.post("/api/lines/send", json={"to": "alice", "body": "hi alice"}, headers=auth(bob))
    client.post(f"/api/gate/{m2.json()['id']}", json={"verdict": "approve"})
    return line_id, alice, bob


def test_archive_on_request_moves_the_history_and_the_line_continues(client, make_agent):
    line_id, alice, _ = converse(client, make_agent)
    before = client.get(f"/api/lines/{line_id}/messages").json()
    assert [m["body"] for m in before] == ["hi bob", "go", "hi alice"]

    resp = client.post(f"/api/lines/{line_id}/archive")
    assert resp.status_code == 200, resp.text
    archive = resp.json()
    assert archive["reason"] == "operator"
    assert archive["message_count"] == 3
    assert {archive["agent_a_name"], archive["agent_b_name"]} == {"alice", "bob"}
    assert archive["transcript"] is None  # summaries travel light

    after = client.get(f"/api/lines/{line_id}/messages").json()
    assert len(after) == 1 and after[0]["kind"] == "system"
    assert "archived by the operator (3 messages)" in after[0]["body"]
    line = client.get(f"/api/lines/{line_id}").json()
    assert line["state"] == "idle" and line["pending_count"] == 0

    listed = client.get("/api/archive").json()
    assert [a["id"] for a in listed] == [archive["id"]]
    full = client.get(f"/api/archive/{archive['id']}").json()
    assert [m["body"] for m in full["transcript"]] == ["hi bob", "go", "hi alice"]
    assert full["transcript"][0]["gate_note"] == "go"  # verdicts come along

    export = client.get(f"/api/archive/{archive['id']}/export")
    assert export.status_code == 200
    assert export.headers["content-disposition"].startswith("attachment; filename=")
    assert json.loads(export.text)["transcript"][2]["body"] == "hi alice"

    # the line keeps working afterwards
    again = client.post(
        "/api/lines/send", json={"to": "bob", "body": "round two"}, headers=auth(alice)
    )
    assert again.status_code == 201, again.text


def test_archiving_a_line_with_a_held_message_releases_it(client, make_agent):
    _, alice = make_agent("alice")
    make_agent("bob")
    held = client.post(
        "/api/lines/send", json={"to": "bob", "body": "risky"}, headers=auth(alice)
    ).json()
    assert held["status"] == "pending_gate"

    archive = client.post(f"/api/lines/{held['line_id']}/archive").json()
    full = client.get(f"/api/archive/{archive['id']}").json()
    assert full["transcript"][0]["status"] == "pending_gate"  # archived as it stood
    assert client.get("/api/gate/pending").json() == []
    assert client.get(f"/api/lines/{held['line_id']}").json()["state"] == "idle"


def test_removing_an_agent_archives_its_lines_and_drops_them(client, make_agent):
    line_id, _, _ = converse(client, make_agent)
    client.post("/api/operator/send", json={"to": "alice", "body": "hello alice"})
    alice_id = client.get("/api/agents/alice").json()["id"]
    assert len(client.get("/api/lines").json()) == 2

    assert client.delete("/api/agents/alice").status_code == 200
    remaining = client.get("/api/lines").json()
    assert all(alice_id not in (line["agent_a"], line["agent_b"]) for line in remaining)
    assert client.get(f"/api/lines/{line_id}").status_code == 404

    archives = client.get("/api/archive").json()
    assert len(archives) == 2
    assert {a["reason"] for a in archives} == {"agent_removed"}
    assert all("alice" in (a["agent_a_name"], a["agent_b_name"]) for a in archives)
    assert {a["message_count"] for a in archives} == {3, 1}


def test_lines_of_agents_removed_before_archiving_existed_are_archived_at_startup(
    client, make_agent, config
):
    line_id, _, _ = converse(client, make_agent)
    with psycopg.connect(config.database_url, autocommit=True) as conn:  # the pre-D20 state
        conn.execute("UPDATE agents SET removed_at = now() WHERE name = 'bob'")
    assert client.get("/api/archive").json() == []

    with TestClient(create_app(config)) as fresh:
        assert fresh.get(f"/api/lines/{line_id}").status_code == 404
        archives = fresh.get("/api/archive").json()
        assert [a["reason"] for a in archives] == ["agent_removed"]
        assert archives[0]["message_count"] == 3


def test_delete_archive(client, make_agent):
    line_id, _, _ = converse(client, make_agent)
    archive = client.post(f"/api/lines/{line_id}/archive").json()
    assert client.delete(f"/api/archive/{archive['id']}").status_code == 204
    assert client.get(f"/api/archive/{archive['id']}").status_code == 404
    assert client.get("/api/archive").json() == []
