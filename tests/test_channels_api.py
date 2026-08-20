"""Channel registry API: attach/heartbeat/detach semantics, the attach summary,
channel replacement, endpoint validation. (Push mechanics are in test_delivery.py.)"""

from __future__ import annotations

from conftest import auth

DEAD_ENDPOINT = "http://127.0.0.1:9/"  # discard port: nothing listens


def attach(client, name, token, endpoint=DEAD_ENDPOINT, channel_token="ct-secret"):
    return client.post(
        f"/api/agents/{name}/attach",
        json={"endpoint": endpoint, "channel_token": channel_token},
        headers=auth(token),
    )


def test_attach_marks_connected_and_returns_roster(client, make_agent):
    make_agent("alice")
    _, bob_token = make_agent("bob", description="fake infra agent")

    resp = attach(client, "bob", bob_token)
    assert resp.status_code == 200, resp.text
    summary = resp.json()
    assert summary["agent"]["name"] == "bob"
    assert summary["agent"]["status"] == "connected"
    assert summary["queued"] == 0 and summary["lines"] == []
    roster = {p["name"]: p for p in summary["roster"]}
    assert set(roster) == {"alice", "operator"}  # everyone but me; removed agents excluded
    assert roster["operator"]["description"] == "the human operator of this courtyard"
    assert client.get("/api/agents/bob").json()["status"] == "connected"


def test_attach_summary_reports_lines_turn_and_backlog(client, make_agent):
    _, alice_token = make_agent("alice")
    _, bob_token = make_agent("bob")
    sent = client.post(
        "/api/lines/send", json={"to": "bob", "body": "ping"}, headers=auth(alice_token)
    ).json()
    client.post(f"/api/gate/{sent['id']}", json={"verdict": "approve"})  # queued, no channel

    summary = attach(client, "bob", bob_token).json()
    assert summary["queued"] == 1
    (line,) = summary["lines"]
    assert line["peer"] == "alice" and line["state"] == "awaiting_reply"
    assert line["your_turn"] is True
    assert line["in_flight"]["id"] == sent["id"] and line["in_flight"]["body"] == "ping"


def test_pending_gate_message_never_leaks_into_attach_summary(client, make_agent):
    _, alice_token = make_agent("alice")
    _, bob_token = make_agent("bob")
    client.post("/api/lines/send", json={"to": "bob", "body": "secret"}, headers=auth(alice_token))

    summary = attach(client, "bob", bob_token).json()
    assert summary["queued"] == 0
    (line,) = summary["lines"]
    assert line["state"] == "pending_gate"
    assert line["your_turn"] is False and line["in_flight"] is None


def test_attach_requires_the_agents_own_token(client, make_agent):
    make_agent("alice")
    _, bob_token = make_agent("bob")
    resp = attach(client, "alice", bob_token)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "not_allowed"


def test_attach_rejects_nonlocal_endpoint(client, make_agent):
    _, token = make_agent("alice")
    resp = attach(client, "alice", token, endpoint="http://example.com:8080/")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_endpoint"


def test_heartbeat_requires_attach(client, make_agent):
    _, token = make_agent("alice")
    resp = client.post("/api/agents/alice/heartbeat", headers=auth(token))
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "not_attached"


def test_heartbeat_reports_queued_count(client, make_agent):
    _, alice_token = make_agent("alice")
    _, bob_token = make_agent("bob")
    attach(client, "bob", bob_token)
    beat = client.post("/api/agents/bob/heartbeat", headers=auth(bob_token)).json()
    assert beat == {"ok": True, "status": "connected", "queued": 0}

    sent = client.post(
        "/api/lines/send", json={"to": "bob", "body": "hi"}, headers=auth(alice_token)
    ).json()
    client.post(f"/api/gate/{sent['id']}", json={"verdict": "approve"})  # push fails: dead port
    beat = client.post("/api/agents/bob/heartbeat", headers=auth(bob_token)).json()
    assert beat["queued"] == 1


def test_detach_marks_gone_and_is_idempotent_only_while_attached(client, make_agent):
    _, token = make_agent("bob")
    attach(client, "bob", token)
    assert client.post("/api/agents/bob/detach", headers=auth(token)).status_code == 200
    assert client.get("/api/agents/bob").json()["status"] == "gone"
    resp = client.post("/api/agents/bob/detach", headers=auth(token))
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "not_attached"


def test_liveness_gone_agent_can_still_receive_sends_and_reattach(client, make_agent):
    """`gone` is a liveness state, not removal: messages queue up, and the agent comes back."""
    _, alice_token = make_agent("alice")
    _, bob_token = make_agent("bob")
    attach(client, "bob", bob_token)
    client.post("/api/agents/bob/detach", headers=auth(bob_token))

    resp = client.post(
        "/api/lines/send", json={"to": "bob", "body": "you there?"}, headers=auth(alice_token)
    )
    assert resp.status_code == 201  # queues at the gate; nothing about liveness blocks it
    summary = attach(client, "bob", bob_token).json()
    assert summary["agent"]["status"] == "connected"


def test_removed_agent_cannot_attach(client, make_agent):
    _, token = make_agent("bob")
    client.delete("/api/agents/bob")
    resp = attach(client, "bob", token)
    assert resp.status_code == 401  # removal revokes the token


def test_reattach_replaces_channel_and_warns_when_previous_was_live(client, make_agent):
    _, token = make_agent("bob")
    attach(client, "bob", token, channel_token="first")
    attach(client, "bob", token, channel_token="second")  # still connected: suspicious

    lines = client.get("/api/lines").json()
    assert len(lines) == 1  # the operator<->bob line carrying the warning
    messages = client.get(f"/api/lines/{lines[0]['id']}/messages").json()
    assert any(
        m["kind"] == "system" and "two sessions" in m["body"] and m["recipient"] is None
        for m in messages
    )


def test_reattach_after_detach_is_silent(client, make_agent):
    _, token = make_agent("bob")
    attach(client, "bob", token)
    client.post("/api/agents/bob/detach", headers=auth(token))
    attach(client, "bob", token)
    assert client.get("/api/lines").json() == []  # no warning line
