"""D24 — end shift closes the books; incidents re-deliver (design §8.1, §5.4 rule 7, §6.4).

End shift releases every non-idle line and marks the unfinished messages `expired` (kept
in history, nothing deleted). On attach, a delivered-but-unanswered in-flight message is
re-armed to `queued` for the backlog push (R1) — unless it expired, which is the point of
the status.
"""

from __future__ import annotations

from conftest import auth

DEAD_ENDPOINT = "http://127.0.0.1:9/push"  # nothing listens: pushes fail, messages stay queued


def send(client, token, to, body="hello"):
    return client.post("/api/lines/send", json={"to": to, "body": body}, headers=auth(token))


def pull_inbox(client, name, token):
    return client.get(f"/api/agents/{name}/inbox", headers=auth(token)).json()


def decide(client, message_id, verdict, note=None):
    return client.post(f"/api/gate/{message_id}", json={"verdict": verdict, "note": note})


def attach(client, name, token):
    resp = client.post(
        f"/api/agents/{name}/attach",
        json={"endpoint": DEAD_ENDPOINT, "channel_token": "ct"},
        headers=auth(token),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def line_state(client, line_id):
    return client.get(f"/api/lines/{line_id}").json()


def line_messages(client, line_id):
    return client.get(f"/api/lines/{line_id}/messages").json()


def end_shift(client):
    """Start a shift (nothing spawns: puppets have no launch profile) and end it, forcing
    past the mid-conversation confirm the busy lines would raise."""
    assert client.post("/api/shift/start").status_code == 200
    resp = client.post("/api/shift/end", json={"force": True})
    assert resp.status_code == 200, resp.text
    return resp.json()


def delivered_unanswered(client, make_agent):
    """alice -> bob, approved and pulled by bob, never answered: line awaiting bob."""
    _, alice = make_agent("alice")
    _, bob_token = make_agent("bob")
    msg = send(client, alice, "bob", "q1").json()
    decide(client, msg["id"], "approve")
    (pulled,) = pull_inbox(client, "bob", bob_token)
    assert pulled["status"] == "delivered"
    return msg, bob_token


class TestEndShiftClosesTheBooks:
    def test_awaiting_reply_line_expires_and_goes_idle(self, client, make_agent):
        msg, _ = delivered_unanswered(client, make_agent)

        end_shift(client)

        line = line_state(client, msg["line_id"])
        assert line["state"] == "idle" and line["awaiting_from"] is None
        history = line_messages(client, msg["line_id"])
        by_id = {m["id"]: m for m in history}
        assert by_id[msg["id"]]["status"] == "expired"  # kept, not deleted
        assert any(
            m["kind"] == "system" and "expired at end of shift" in m["body"] for m in history
        )

    def test_gate_held_message_expires_too(self, client, make_agent):
        _, alice = make_agent("alice")
        make_agent("bob")
        msg = send(client, alice, "bob", "held").json()
        assert msg["status"] == "pending_gate"

        end_shift(client)

        assert line_state(client, msg["line_id"])["state"] == "idle"
        history = line_messages(client, msg["line_id"])
        assert {m["id"]: m["status"] for m in history}[msg["id"]] == "expired"
        assert any("held at the gate expired" in m["body"] for m in history)
        assert client.get("/api/gate/pending").json() == []

    def test_queued_in_flight_expires_and_never_redelivers(self, client, make_agent):
        # Approved but bob never pulled it: in flight as `queued`.
        _, alice = make_agent("alice")
        _, bob_token = make_agent("bob")
        msg = send(client, alice, "bob", "q1").json()
        decide(client, msg["id"], "approve")

        end_shift(client)

        assert {m["id"]: m["status"] for m in line_messages(client, msg["line_id"])}[
            msg["id"]
        ] == "expired"
        assert pull_inbox(client, "bob", bob_token) == []  # expired is not queued

    def test_idle_lines_are_left_alone(self, client, make_agent):
        _, alice = make_agent("alice")
        _, bob_token = make_agent("bob")
        msg = send(client, alice, "bob", "q1").json()
        decide(client, msg["id"], "approve")
        pull_inbox(client, "bob", bob_token)
        reply = send(client, bob_token, "alice", "a1").json()
        decide(client, reply["id"], "approve")
        before = line_messages(client, msg["line_id"])

        end_shift(client)

        assert line_messages(client, msg["line_id"]) == before  # no entry, nothing touched


class TestRearmOnAttach:
    def test_delivered_unanswered_is_requeued_with_a_note(self, client, make_agent):
        msg, bob_token = delivered_unanswered(client, make_agent)

        summary = attach(client, "bob", bob_token)

        assert summary["queued"] == 1  # the re-armed message rides the normal backlog
        history = line_messages(client, msg["line_id"])
        by_id = {m["id"]: m for m in history}
        assert by_id[msg["id"]]["status"] == "queued"
        assert any(m["kind"] == "system" and "redelivered" in m["body"] for m in history)
        # the line still awaits bob — the obligation is unchanged, now dischargeable
        line = line_state(client, msg["line_id"])
        assert line["state"] == "awaiting_reply"
        (pulled,) = pull_inbox(client, "bob", bob_token)
        assert pulled["id"] == msg["id"] and pulled["status"] == "delivered"

    def test_expired_messages_are_not_resurrected(self, client, make_agent):
        msg, bob_token = delivered_unanswered(client, make_agent)
        end_shift(client)

        summary = attach(client, "bob", bob_token)

        assert summary["queued"] == 0
        assert {m["id"]: m["status"] for m in line_messages(client, msg["line_id"])}[
            msg["id"]
        ] == "expired"
        assert pull_inbox(client, "bob", bob_token) == []

    def test_answered_messages_are_left_alone(self, client, make_agent):
        _, alice = make_agent("alice")
        _, bob_token = make_agent("bob")
        msg = send(client, alice, "bob", "q1").json()
        decide(client, msg["id"], "approve")
        pull_inbox(client, "bob", bob_token)
        reply = send(client, bob_token, "alice", "a1").json()
        decide(client, reply["id"], "approve")

        summary = attach(client, "bob", bob_token)

        assert summary["queued"] == 0
        assert {m["id"]: m["status"] for m in line_messages(client, msg["line_id"])}[
            msg["id"]
        ] == "delivered"

    def test_reattach_rearms_again_for_each_new_session(self, client, make_agent):
        # Session 1 got the redelivery and pulled it, then died unanswered; session 2
        # must get it again — every new session sees the outstanding obligation.
        msg, bob_token = delivered_unanswered(client, make_agent)
        attach(client, "bob", bob_token)
        pull_inbox(client, "bob", bob_token)  # session 1 read it, never answered
        client.post("/api/agents/bob/detach", headers=auth(bob_token))

        summary = attach(client, "bob", bob_token)

        assert summary["queued"] == 1
        (pulled,) = pull_inbox(client, "bob", bob_token)
        assert pulled["id"] == msg["id"]
