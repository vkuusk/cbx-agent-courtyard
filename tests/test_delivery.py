"""Delivery push over real HTTP: hub pushes to live channel listeners; failure paths
leave messages queued for the pull path and re-attach backlog (design §6.1, §6.4)."""

from __future__ import annotations

import time

import pytest

from courtyard.common.client import ChannelReceiver, HubClient


class Listener:
    """A registered, attached agent with a real receive endpoint collecting pushes."""

    def __init__(self, hub_url: str, name: str, type: str = "puppet"):
        admin = HubClient(hub_url)
        _agent, token = admin.register_agent(name, type)
        admin.close()
        self.received: list = []
        self.client = HubClient(hub_url, name, token)
        self.receiver = ChannelReceiver(self.received.append)
        self.summary = self.client.attach(self.receiver.endpoint, self.receiver.channel_token)

    def wait_for(self, count: int, timeout: float = 5.0) -> list:
        deadline = time.monotonic() + timeout
        while len(self.received) < count:
            if time.monotonic() > deadline:
                raise AssertionError(f"got {len(self.received)}/{count}: {self.received}")
            time.sleep(0.02)
        return self.received


@pytest.fixture()
def hub(live_hub):
    return live_hub()


@pytest.fixture()
def operator(hub):
    op = HubClient(hub)
    yield op
    op.close()


def test_approved_message_is_pushed_to_the_recipient(hub, operator):
    alice = Listener(hub, "alice")
    bob = Listener(hub, "bob")

    sent = alice.client.send("bob", "can you deploy?")
    assert sent.status == "pending_gate"
    assert bob.received == []  # nothing leaks pre-approval

    operator.decide(sent.id, "approve")
    (got,) = bob.wait_for(1)
    assert got.id == sent.id and got.body == "can you deploy?"
    # the pushed payload is the pre-push snapshot; the stored row flips to delivered
    stored = operator.line_messages(sent.line_id)
    assert next(m for m in stored if m.id == sent.id).status == "delivered"


def test_auto_pass_send_reports_delivered_synchronously(hub, operator):
    alice = Listener(hub, "alice")
    bob = Listener(hub, "bob")
    first = alice.client.send("bob", "opening")
    operator.set_mode(first.line_id, "auto_pass")
    operator.decide(first.id, "approve")
    bob.wait_for(1)
    bob.client.send("alice", "reply")  # closes the turn
    alice.wait_for(1)

    sent = alice.client.send("bob", "second round")
    assert sent.status == "delivered"  # push succeeded before send() returned
    assert bob.wait_for(2)[1].body == "second round"


def test_push_failure_leaves_queued_marks_stale_and_pull_recovers(hub, operator):
    alice = Listener(hub, "alice")
    bob = Listener(hub, "bob")
    first = alice.client.send("bob", "opening")
    operator.set_mode(first.line_id, "auto_pass")
    operator.decide(first.id, "approve")
    bob.wait_for(1)
    bob.client.send("alice", "reply")
    alice.wait_for(1)

    bob.receiver.stop()  # simulated crash: no detach, channel registration remains
    sent = alice.client.send("bob", "are you there?")
    assert sent.status == "queued"
    assert next(a for a in operator.agents() if a.name == "bob").status == "stale"

    pulled = bob.client.inbox()  # the pull path picks it up
    assert [m.id for m in pulled] == [sent.id]
    assert pulled[0].status == "delivered"


def test_wrong_channel_token_is_rejected_and_message_stays_queued(hub, operator):
    alice = Listener(hub, "alice")
    bob = Listener(hub, "bob")
    bob.client.detach()
    bob.client.attach(bob.receiver.endpoint, "not-the-real-token")

    sent = alice.client.send("bob", "psst")
    operator.decide(sent.id, "approve")
    time.sleep(0.3)
    assert bob.received == []  # the listener refused the push
    assert next(m.id for m in bob.client.inbox()) == sent.id  # still queued until pulled


def test_human_recipient_is_delivered_immediately(hub, operator):
    alice = Listener(hub, "alice")
    sent = alice.client.send("operator", "status report")
    decided = operator.decide(sent.id, "approve")
    assert decided.status == "delivered"  # the WebUI is the operator's tunnel


def test_backlog_redelivers_in_order_on_reattach(hub, operator):
    alice = Listener(hub, "alice")
    bob = Listener(hub, "bob")
    first = alice.client.send("bob", "opening")
    operator.set_mode(first.line_id, "auto_pass")
    operator.decide(first.id, "approve")
    bob.wait_for(1)
    bob.client.send("alice", "reply")
    alice.wait_for(1)

    bob.receiver.stop()  # crash
    m1 = alice.client.send("bob", "first while you were away")
    lines = operator.lines()
    m2 = operator._call(  # operator note joins the backlog behind the message
        "POST", f"/api/lines/{lines[0].id}/note", {"target": "bob", "body": "note for bob"}
    )
    assert m1.status == "queued" and m2["status"] == "queued"

    bob2 = ChannelReceiver(bob.received.append)
    summary = bob.client.attach(bob2.endpoint, bob2.channel_token)
    assert summary.queued == 2
    got = bob.wait_for(3)  # 1 from before the crash + the 2 re-delivered
    assert [m.body for m in got[1:]] == ["first while you were away", "note for bob"]
    stored = {m.id: m for m in operator.line_messages(m1.line_id)}
    assert stored[m1.id].status == "delivered"
    assert bob.client.inbox() == []  # nothing left queued


def test_gate_return_notice_is_pushed_to_the_sender(hub, operator):
    alice = Listener(hub, "alice")
    Listener(hub, "bob")
    sent = alice.client.send("bob", "half-baked idea")
    operator.decide(sent.id, "return", "please add the error budget numbers")

    (notice,) = alice.wait_for(1)
    assert notice.kind == "system"
    assert "returned to you" in notice.body
    assert "error budget numbers" in notice.body
