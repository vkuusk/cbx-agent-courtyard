"""Step 5 — the operator as participant: compose endpoint, ungated operator lines with
normal turn rules, note targeting incl. "both", the operator inbox."""

from conftest import auth


def op_send(client, to, body="hello from the operator"):
    return client.post("/api/operator/send", json={"to": to, "body": body})


def test_operator_send_is_never_gated(client, make_agent):
    make_agent("alice")
    resp = op_send(client, "alice")
    assert resp.status_code == 201, resp.text
    message = resp.json()
    assert message["sender_name"] == "operator"
    assert message["status"] == "queued"  # not pending_gate; queued (no channel attached)

    line = client.get(f"/api/lines/{message['line_id']}").json()
    assert line["mode"] == "auto_pass" and line["state"] == "awaiting_reply"


def test_operator_lines_keep_normal_turn_rules(client, make_agent):
    _, alice = make_agent("alice")
    op_send(client, "alice", "first")
    resp = op_send(client, "alice", "second before a reply")
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "turn_violation"

    # alice's reply closes the turn and is itself ungated on this line
    reply = client.post(
        "/api/lines/send", json={"to": "operator", "body": "reply"}, headers=auth(alice)
    )
    assert reply.status_code == 201
    assert reply.json()["status"] == "delivered"  # human recipient: WebUI is the tunnel


def test_agent_initiated_operator_line_is_ungated_too(client, make_agent):
    _, alice = make_agent("alice")
    sent = client.post(
        "/api/lines/send", json={"to": "operator", "body": "hi"}, headers=auth(alice)
    ).json()
    assert sent["status"] == "delivered"
    assert client.get(f"/api/lines/{sent['line_id']}").json()["mode"] == "auto_pass"


def test_mode_toggle_rejected_on_operator_lines(client, make_agent):
    make_agent("alice")
    message = op_send(client, "alice").json()
    resp = client.post(f"/api/lines/{message['line_id']}/mode", json={"mode": "supervised"})
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "not_allowed"


def test_note_to_both_reaches_both_participants(client, make_agent):
    _, alice = make_agent("alice")
    _, bob = make_agent("bob")
    first = client.post(
        "/api/lines/send", json={"to": "bob", "body": "make the line"}, headers=auth(alice)
    ).json()
    client.post(f"/api/gate/{first['id']}", json={"verdict": "drop"})

    resp = client.post(
        f"/api/lines/{first['line_id']}/note", json={"body": "you two: use repo X"}
    )  # target omitted -> both
    assert resp.status_code == 201
    notes = resp.json()
    assert len(notes) == 2
    assert {n["recipient_name"] for n in notes} == {"alice", "bob"}

    alice_inbox = client.get("/api/agents/alice/inbox", headers=auth(alice)).json()
    bob_inbox = client.get("/api/agents/bob/inbox", headers=auth(bob)).json()
    assert [m["body"] for m in bob_inbox] == ["you two: use repo X"]
    assert "you two: use repo X" in [m["body"] for m in alice_inbox]


def test_note_rejected_on_operator_own_lines(client, make_agent):
    make_agent("alice")
    message = op_send(client, "alice").json()
    resp = client.post(f"/api/lines/{message['line_id']}/note", json={"body": "note"})
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "not_allowed"


def test_operator_inbox_returns_newest_first(client, make_agent):
    _, alice = make_agent("alice")
    op_send(client, "alice", "opening")
    client.post(
        "/api/lines/send", json={"to": "operator", "body": "reply one"}, headers=auth(alice)
    )
    op_send(client, "alice", "next round")
    client.post(
        "/api/lines/send", json={"to": "operator", "body": "reply two"}, headers=auth(alice)
    )

    inbox = client.get("/api/operator/inbox").json()
    assert [m["body"] for m in inbox] == ["reply two", "reply one"]
    assert all(m["recipient_name"] == "operator" for m in inbox)
    # non-consuming: reading again returns the same
    assert [m["body"] for m in client.get("/api/operator/inbox").json()] == [
        "reply two",
        "reply one",
    ]
