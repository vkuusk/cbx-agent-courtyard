"""Threads (design threads.md, D34) — one bounded exchange about one ask.

Serial v1: a line holds at most one open thread. The sender declares boundaries (the
hub never infers them): the first message on a line with no open thread opens one,
declared or not; a declared new ask while one is open is refused like a turn violation.
Close is a dedicated protocol event, initiator-only, resolving the reply obligation.
End shift expires open threads (extends D24).
"""

from __future__ import annotations

from conftest import auth


def send(client, token, to, body="hello", new_thread=False):
    return client.post(
        "/api/lines/send",
        json={"to": to, "body": body, "new_thread": new_thread},
        headers=auth(token),
    )


def close_thread(client, token, peer):
    return client.post("/api/lines/close-thread", json={"peer": peer}, headers=auth(token))


def decide(client, message_id, verdict, note=None):
    return client.post(f"/api/gate/{message_id}", json={"verdict": verdict, "note": note})


def pull_inbox(client, name, token):
    return client.get(f"/api/agents/{name}/inbox", headers=auth(token)).json()


def line_state(client, line_id):
    return client.get(f"/api/lines/{line_id}").json()


def line_threads(client, line_id):
    return client.get(f"/api/lines/{line_id}/threads").json()


def line_messages(client, line_id):
    return client.get(f"/api/lines/{line_id}/messages").json()


def auto_pass(client, line_id):
    assert client.post(f"/api/lines/{line_id}/mode", json={"mode": "auto_pass"}).status_code == 200


def exchange(client, make_agent):
    """alice asks, bob answers, on an auto-pass line: idle line, open thread."""
    _, alice = make_agent("alice")
    _, bob = make_agent("bob")
    msg = send(client, alice, "bob", "q1").json()
    decide(client, msg["id"], "approve")
    pull_inbox(client, "bob", bob)
    reply = send(client, bob, "alice", "a1").json()
    decide(client, reply["id"], "approve")
    return msg, alice, bob


class TestOpeningAndContinuing:
    def test_first_message_opens_a_thread(self, client, make_agent):
        agent_a, alice = make_agent("alice")
        make_agent("bob")

        msg = send(client, alice, "bob", "q1").json()

        assert msg["thread_id"] is not None
        (thread,) = line_threads(client, msg["line_id"])
        assert thread["id"] == msg["thread_id"]
        assert thread["state"] == "open" and thread["ended_at"] is None
        assert thread["opened_by"] == agent_a["id"] and thread["opened_by_name"] == "alice"
        assert line_state(client, msg["line_id"])["open_thread"] == thread["id"]

    def test_replies_and_followups_continue_the_open_thread(self, client, make_agent):
        msg, alice, _bob = exchange(client, make_agent)

        followup = send(client, alice, "bob", "q2").json()

        history = line_messages(client, msg["line_id"])
        assert {m["thread_id"] for m in history if m["kind"] == "message"} == {msg["thread_id"]}
        assert followup["thread_id"] == msg["thread_id"]
        assert len(line_threads(client, msg["line_id"])) == 1

    def test_declared_new_ask_is_refused_while_a_thread_is_open(self, client, make_agent):
        msg, alice, _bob = exchange(client, make_agent)

        resp = send(client, alice, "bob", "unrelated", new_thread=True)

        assert resp.status_code == 409
        error = resp.json()["error"]
        assert error["code"] == "thread_open"
        assert error["opened_by"] == "alice"
        # nothing was filed into the open thread
        assert (
            len([m for m in line_messages(client, msg["line_id"]) if m["kind"] == "message"]) == 2
        )

    def test_declaring_on_a_quiet_line_just_opens_one(self, client, make_agent):
        _, alice = make_agent("alice")
        make_agent("bob")

        msg = send(client, alice, "bob", "q1", new_thread=True).json()

        assert msg["thread_id"] is not None
        assert msg["status"] == "pending_gate"  # the declaration changes nothing else

    def test_gated_message_opens_the_thread_at_send(self, client, make_agent):
        """The thread records the ask when it is made; a return keeps it open — the
        revised message is the same ask, so it continues the same thread."""
        _, alice = make_agent("alice")
        make_agent("bob")
        msg = send(client, alice, "bob", "q1").json()
        assert msg["status"] == "pending_gate" and msg["thread_id"] is not None

        decide(client, msg["id"], "return", "reword this")
        revised = send(client, alice, "bob", "q1 reworded").json()

        assert revised["thread_id"] == msg["thread_id"]
        (thread,) = line_threads(client, msg["line_id"])
        assert thread["state"] == "open"


class TestClosing:
    def test_initiator_close_ends_the_thread_and_tells_the_peer(self, client, make_agent):
        msg, alice, bob = exchange(client, make_agent)

        closed = close_thread(client, alice, "bob")

        assert closed.status_code == 200, closed.text
        assert closed.json()["state"] == "closed" and closed.json()["ended_at"] is not None
        line = line_state(client, msg["line_id"])
        assert line["open_thread"] is None and line["state"] == "idle"
        # the peer learns from a fixed system line, delivered through the normal path
        (notice,) = pull_inbox(client, "bob", bob)
        assert notice["kind"] == "system" and notice["body"] == "thread closed by alice"
        assert notice["thread_id"] == msg["thread_id"]

    def test_next_ask_after_close_opens_a_new_thread(self, client, make_agent):
        msg, alice, _bob = exchange(client, make_agent)
        close_thread(client, alice, "bob")

        second = send(client, alice, "bob", "q2").json()

        assert second["thread_id"] != msg["thread_id"]
        states = [t["state"] for t in line_threads(client, msg["line_id"])]
        assert states == ["closed", "open"]

    def test_close_resolves_the_reply_owed_by_the_closer(self, client, make_agent):
        # bob's answer was a clarifying question: the line awaits alice, who closes
        # instead of answering — a closed thread never leaves a line stuck (D34).
        msg, alice, bob = exchange(client, make_agent)
        auto_pass(client, msg["line_id"])
        pull_inbox(client, "alice", alice)
        send(client, bob, "alice", "which env?")
        assert line_state(client, msg["line_id"])["state"] == "awaiting_reply"

        assert close_thread(client, alice, "bob").status_code == 200

        line = line_state(client, msg["line_id"])
        assert line["state"] == "idle" and line["awaiting_from"] is None

    def test_close_resolves_the_reply_owed_to_the_closer(self, client, make_agent):
        # alice asked and is still waiting, but no longer needs the answer.
        _, alice = make_agent("alice")
        make_agent("bob")
        msg = send(client, alice, "bob", "q1").json()
        decide(client, msg["id"], "approve")
        assert line_state(client, msg["line_id"])["state"] == "awaiting_reply"

        assert close_thread(client, alice, "bob").status_code == 200

        assert line_state(client, msg["line_id"])["state"] == "idle"

    def test_only_the_initiator_closes(self, client, make_agent):
        msg, _alice, bob = exchange(client, make_agent)

        resp = close_thread(client, bob, "alice")

        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "not_thread_initiator"
        assert line_state(client, msg["line_id"])["open_thread"] == msg["thread_id"]

    def test_close_with_nothing_open_is_refused(self, client, make_agent):
        _msg, alice, _bob = exchange(client, make_agent)
        close_thread(client, alice, "bob")

        resp = close_thread(client, alice, "bob")

        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "no_open_thread"

    def test_close_waits_for_the_gate(self, client, make_agent):
        _msg, alice, _bob = exchange(client, make_agent)
        held = send(client, alice, "bob", "one more thing").json()
        assert held["status"] == "pending_gate"

        resp = close_thread(client, alice, "bob")

        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "gate_pending"

    def test_the_answer_envelope_points_only_the_initiator_at_the_close_tool(
        self, client, make_agent
    ):
        msg, alice, bob = exchange(client, make_agent)
        auto_pass(client, msg["line_id"])

        (delivered,) = pull_inbox(client, "alice", alice)  # bob's answer to alice's ask

        assert "courtyard_close_thread" in delivered["rendered"]
        # bob asks a clarifying question inside alice's thread; her answer closes his
        # exchange, but he is not the initiator — no pointer at the close tool for him
        send(client, bob, "alice", "which env?")
        pull_inbox(client, "alice", alice)
        send(client, alice, "bob", "prod")
        (answer,) = pull_inbox(client, "bob", bob)
        assert answer["reply_to"] is not None
        assert "courtyard_close_thread" not in answer["rendered"]
        assert "is complete" in answer["rendered"]


class TestOperatorThreads:
    def test_operator_opens_without_declaring_and_closes_via_the_pane_op(self, client, make_agent):
        make_agent("bob")
        msg = client.post("/api/operator/send", json={"to": "bob", "body": "status?"}).json()
        assert msg["thread_id"] is not None

        resp = client.post("/api/operator/close-thread", json={"peer": "bob"})

        assert resp.status_code == 200, resp.text
        assert resp.json()["state"] == "closed"
        assert line_state(client, msg["line_id"])["state"] == "idle"

    def test_agent_cannot_close_the_operators_thread(self, client, make_agent):
        _, bob = make_agent("bob")
        client.post("/api/operator/send", json={"to": "bob", "body": "status?"})

        resp = close_thread(client, bob, "operator")

        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "not_thread_initiator"


class TestBudgets:
    """D34 §5 item 2: backpressure per task. A reply always passes; the send that would
    grow a spent thread with a fresh ask locks it (committed even though the send is
    refused) and both sides are told. Operator threads are never locked (D9 analog)."""

    def set_budget(self, client, n):
        resp = client.patch("/api/settings", json={"thread_budget": n})
        assert resp.status_code == 200, resp.text

    def test_the_send_that_grows_a_spent_thread_locks_it(self, client, make_agent):
        self.set_budget(client, 2)  # q + a spends it
        msg, alice, _bob = exchange(client, make_agent)

        resp = send(client, alice, "bob", "one more thing")

        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "thread_locked"
        (thread,) = line_threads(client, msg["line_id"])
        assert thread["state"] == "locked" and thread["ended_at"] is not None
        line = line_state(client, msg["line_id"])
        assert line["open_thread"] is None and line["state"] == "idle"
        history = line_messages(client, msg["line_id"])
        notices = [m for m in history if m["kind"] == "system"]
        assert len(notices) == 2  # both sides told, durably
        assert all("thread locked" in m["body"] for m in notices)
        assert {m["recipient_name"] for m in notices} == {"alice", "bob"}
        assert all(m["thread_id"] == msg["thread_id"] for m in notices)
        # the refused message itself is nowhere in history
        assert not any("one more thing" in m["body"] for m in history)

    def test_a_reply_passes_even_past_the_budget(self, client, make_agent):
        self.set_budget(client, 1)  # the ask alone spends it
        _, alice = make_agent("alice")
        _, bob = make_agent("bob")
        msg = send(client, alice, "bob", "q1").json()
        decide(client, msg["id"], "approve")
        pull_inbox(client, "bob", bob)

        reply = send(client, bob, "alice", "a1")

        assert reply.status_code == 201  # obligations stay dischargeable, always
        (thread,) = line_threads(client, msg["line_id"])
        assert thread["state"] == "open"

    def test_the_next_ask_after_a_lock_opens_a_new_thread(self, client, make_agent):
        self.set_budget(client, 2)
        msg, alice, _bob = exchange(client, make_agent)
        assert send(client, alice, "bob", "over budget").status_code == 409

        second = send(client, alice, "bob", "a different ask")

        assert second.status_code == 201
        assert second.json()["thread_id"] != msg["thread_id"]
        states = [t["state"] for t in line_threads(client, msg["line_id"])]
        assert states == ["locked", "open"]  # the lock survived its own refusal

    def test_operator_threads_are_never_locked(self, client, make_agent):
        self.set_budget(client, 1)
        _, bob = make_agent("bob")
        first = client.post("/api/operator/send", json={"to": "bob", "body": "one"}).json()
        pull_inbox(client, "bob", bob)
        send(client, bob, "operator", "reply")  # count now 2, well past budget 1

        followup = client.post("/api/operator/send", json={"to": "bob", "body": "two"})

        assert followup.status_code == 201
        assert followup.json()["thread_id"] == first["thread_id"]

    def test_zero_budget_means_unbudgeted(self, client, make_agent):
        self.set_budget(client, 0)
        msg, alice, _bob = exchange(client, make_agent)

        resp = send(client, alice, "bob", "more")

        assert resp.status_code == 201
        assert resp.json()["thread_id"] == msg["thread_id"]

    def test_returned_messages_do_not_count(self, client, make_agent):
        self.set_budget(client, 1)
        _, alice = make_agent("alice")
        make_agent("bob")
        first = send(client, alice, "bob", "q1").json()
        decide(client, first["id"], "return", "reword")

        revised = send(client, alice, "bob", "q1 reworded")

        assert revised.status_code == 201  # the returned ask never reached anyone
        assert revised.json()["thread_id"] == first["thread_id"]

    def test_settings_reject_a_negative_budget(self, client):
        assert client.patch("/api/settings", json={"thread_budget": -1}).status_code == 422
        assert client.get("/api/settings").json()["thread_budget"] == 12  # the default


class TestShiftEndAndArchive:
    def end_shift(self, client):
        assert client.post("/api/shift/start").status_code == 200
        assert client.post("/api/shift/end", json={"force": True}).status_code == 200

    def test_end_shift_expires_open_threads_even_on_idle_lines(self, client, make_agent):
        msg, _alice, _bob = exchange(client, make_agent)  # idle line, open thread

        self.end_shift(client)

        (thread,) = line_threads(client, msg["line_id"])
        assert thread["state"] == "expired" and thread["ended_at"] is not None
        assert line_state(client, msg["line_id"])["open_thread"] is None
        history = line_messages(client, msg["line_id"])
        assert any(
            m["kind"] == "system" and m["body"] == "the open thread expired at end of shift"
            for m in history
        )

    def test_closed_threads_are_left_alone_by_shift_end(self, client, make_agent):
        msg, alice, _bob = exchange(client, make_agent)
        close_thread(client, alice, "bob")

        self.end_shift(client)

        (thread,) = line_threads(client, msg["line_id"])
        assert thread["state"] == "closed"

    def test_expired_thread_lets_the_next_ask_open_fresh(self, client, make_agent):
        msg, alice, _bob = exchange(client, make_agent)
        self.end_shift(client)

        second = send(client, alice, "bob", "new day", new_thread=True).json()

        assert second["thread_id"] != msg["thread_id"]

    def test_archiving_a_line_takes_its_threads_with_the_history(self, client, make_agent):
        msg, _alice, _bob = exchange(client, make_agent)

        resp = client.post(f"/api/lines/{msg['line_id']}/archive")

        assert resp.status_code == 200, resp.text
        assert line_threads(client, msg["line_id"]) == []
        assert line_state(client, msg["line_id"])["open_thread"] is None
        # the transcript keeps each message's thread membership
        archive = client.get(f"/api/archive/{resp.json()['id']}").json()
        assert {m["thread_id"] for m in archive["transcript"] if m["kind"] == "message"} == {
            msg["thread_id"]
        }
