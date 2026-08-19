"""Board API integration: full supervised/auto-pass flows, all gate verdicts, release, notes."""

from conftest import auth


def send(client, token, to, body="hello"):
    return client.post("/api/lines/send", json={"to": to, "body": body}, headers=auth(token))


def line_of(client, message):
    return client.get(f"/api/lines/{message['line_id']}").json()


def pull_inbox(client, name, token):
    return client.get(f"/api/agents/{name}/inbox", headers=auth(token)).json()


def decide(client, message_id, verdict, note=None):
    return client.post(f"/api/gate/{message_id}", json={"verdict": verdict, "note": note})


def test_supervised_round_trip(client, make_agent):
    _, alice = make_agent("alice")
    bob_agent, bob = make_agent("bob")

    resp = send(client, alice, "bob", "q1")
    assert resp.status_code == 201
    msg = resp.json()
    assert msg["status"] == "pending_gate"
    line = line_of(client, msg)
    assert line["mode"] == "supervised" and line["state"] == "pending_gate"

    # nobody may send while the gate is pending; nothing is delivered yet
    assert send(client, alice, "bob").json()["error"]["code"] == "gate_pending"
    assert send(client, bob, "alice").json()["error"]["code"] == "gate_pending"
    assert pull_inbox(client, "bob", bob) == []
    assert [p["id"] for p in client.get("/api/gate/pending").json()] == [msg["id"]]

    # approve -> queued, line awaits bob's reply, bob pulls it as delivered
    assert decide(client, msg["id"], "approve").json()["status"] == "queued"
    line = line_of(client, msg)
    assert line["state"] == "awaiting_reply" and line["awaiting_from"] == bob_agent["id"]
    inbox = pull_inbox(client, "bob", bob)
    assert [m["id"] for m in inbox] == [msg["id"]]
    assert inbox[0]["status"] == "delivered" and inbox[0]["sender_name"] == "alice"
    assert pull_inbox(client, "bob", bob) == []  # pull is consuming

    # alice may not send again until bob answers
    resp = send(client, alice, "bob")
    assert resp.status_code == 409
    error = resp.json()["error"]
    assert error["code"] == "turn_violation" and error["awaiting_from"] == bob_agent["id"]

    # bob's reply is gated too; approving it completes the exchange
    reply = send(client, bob, "alice", "a1").json()
    assert reply["status"] == "pending_gate" and reply["reply_to"] == msg["id"]
    decide(client, reply["id"], "approve")
    assert line_of(client, msg)["state"] == "idle"
    assert [m["id"] for m in pull_inbox(client, "alice", alice)] == [reply["id"]]


def test_return_to_sender_flow(client, make_agent):
    _, alice = make_agent("alice")
    _, bob = make_agent("bob")

    msg = send(client, alice, "bob", "vague question").json()
    returned = decide(client, msg["id"], "return", "too vague, add the file path").json()
    assert returned["status"] == "returned"
    assert returned["gate_verdict"] == "return"
    assert line_of(client, msg)["state"] == "idle"

    # bob never sees it; alice gets the system notice carrying the comment
    assert pull_inbox(client, "bob", bob) == []
    notices = pull_inbox(client, "alice", alice)
    assert len(notices) == 1
    notice = notices[0]
    assert notice["kind"] == "system" and notice["sender"] is None
    assert notice["reply_to"] == msg["id"]
    assert "returned" in notice["body"] and "too vague, add the file path" in notice["body"]

    # revise and resend works
    assert send(client, alice, "bob", "revised question").status_code == 201


def test_reject_flow(client, make_agent):
    _, alice = make_agent("alice")
    _, bob = make_agent("bob")

    msg = send(client, alice, "bob", "rude message").json()
    assert decide(client, msg["id"], "reject", "not acceptable").json()["status"] == "rejected"
    assert pull_inbox(client, "bob", bob) == []
    notice = pull_inbox(client, "alice", alice)[0]
    assert "rejected" in notice["body"] and "not acceptable" in notice["body"]
    assert line_of(client, msg)["state"] == "idle"

    # a decided message cannot be decided again
    resp = decide(client, msg["id"], "approve")
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "not_pending"


def test_auto_pass_flow(client, make_agent):
    _, alice = make_agent("alice")
    _, bob = make_agent("bob")

    first = send(client, alice, "bob", "make the line").json()
    decide(client, first["id"], "reject")
    client.post(f"/api/lines/{first['line_id']}/mode", json={"mode": "auto_pass"})

    msg = send(client, alice, "bob", "q").json()
    assert msg["status"] == "queued"
    assert line_of(client, msg)["state"] == "awaiting_reply"
    reply = send(client, bob, "alice", "a").json()
    assert reply["status"] == "queued" and reply["reply_to"] == msg["id"]
    assert line_of(client, msg)["state"] == "idle"
    assert [m["body"] for m in pull_inbox(client, "bob", bob)] == ["q"]
    # alice's pull brings the earlier reject notice plus the reply, in order
    bodies = [m["kind"] for m in pull_inbox(client, "alice", alice)]
    assert bodies == ["system", "message"]


def test_mode_flip_does_not_auto_approve_pending(client, make_agent):
    _, alice = make_agent("alice")
    _, _bob = make_agent("bob")
    msg = send(client, alice, "bob", "held").json()
    client.post(f"/api/lines/{msg['line_id']}/mode", json={"mode": "auto_pass"})
    assert [p["id"] for p in client.get("/api/gate/pending").json()] == [msg["id"]]
    assert send(client, alice, "bob").json()["error"]["code"] == "gate_pending"
    assert decide(client, msg["id"], "approve").json()["status"] == "queued"


def test_release_stuck_line(client, make_agent):
    _, alice = make_agent("alice")
    _, _bob = make_agent("bob")

    first = send(client, alice, "bob", "make the line").json()
    line_id = first["line_id"]

    # release refused while the gate is pending
    resp = client.post(f"/api/lines/{line_id}/release")
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "cannot_release"

    decide(client, first["id"], "approve")  # line now awaits bob, who "died"
    released = client.post(f"/api/lines/{line_id}/release").json()
    assert released["state"] == "idle" and released["awaiting_from"] is None

    history = client.get(f"/api/lines/{line_id}/messages").json()
    log = history[-1]
    assert log["kind"] == "system" and log["recipient"] is None and log["status"] == "delivered"
    assert "released" in log["body"]

    # an idle line cannot be released
    resp = client.post(f"/api/lines/{line_id}/release")
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "cannot_release"


def test_operator_note(client, make_agent):
    _, alice = make_agent("alice")
    _, bob = make_agent("bob")
    make_agent("carol")

    first = send(client, alice, "bob", "make the line").json()
    decide(client, first["id"], "reject")
    line_id = first["line_id"]

    resp = client.post(
        f"/api/lines/{line_id}/note", json={"target": "bob", "body": "context: use repo X"}
    )
    assert resp.status_code == 201
    note = resp.json()
    assert note["kind"] == "operator_note" and note["sender_name"] == "operator"
    assert client.get(f"/api/lines/{line_id}").json()["state"] == "idle"  # turn-exempt
    assert [m["body"] for m in pull_inbox(client, "bob", bob)] == ["context: use repo X"]

    resp = client.post(f"/api/lines/{line_id}/note", json={"target": "carol", "body": "x"})
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "invalid_recipient"


def test_send_validation_errors(client, make_agent):
    _, alice = make_agent("alice")
    make_agent("carol")

    resp = send(client, alice, "alice")
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "invalid_recipient"

    resp = send(client, alice, "nobody")
    assert resp.status_code == 404 and resp.json()["error"]["code"] == "unknown_agent"

    client.delete("/api/agents/carol")
    resp = send(client, alice, "carol")
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "agent_gone"

    resp = send(client, alice, "operator", "x" * 20_000)
    assert resp.status_code == 413 and resp.json()["error"]["code"] == "body_too_large"

    resp = decide(client, "00000000-0000-0000-0000-000000000000", "approve")
    assert resp.status_code == 404 and resp.json()["error"]["code"] == "message_not_found"


def test_line_history_and_after_filter(client, make_agent):
    _, alice = make_agent("alice")
    _, bob = make_agent("bob")

    first = send(client, alice, "bob", "m1").json()
    decide(client, first["id"], "reject")
    line_id = first["line_id"]
    client.post(f"/api/lines/{line_id}/mode", json={"mode": "auto_pass"})
    send(client, bob, "alice", "m3")
    send(client, alice, "bob", "m4")

    history = client.get(f"/api/lines/{line_id}/messages").json()
    assert [m["seq"] for m in history] == [1, 2, 3, 4]  # m1, reject notice, m3, m4
    tail = client.get(f"/api/lines/{line_id}/messages", params={"after": 2}).json()
    assert [m["body"] for m in tail] == ["m3", "m4"]

    # the board lists exactly one line for the pair
    lines = client.get("/api/lines").json()
    assert [ln["id"] for ln in lines] == [line_id]
