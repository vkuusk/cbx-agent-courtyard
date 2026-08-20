"""Puppets end-to-end: two scripted puppets hold a full conversation through the hub over
real HTTP; the supervised gate holds them; violations surface as errors, not crashes."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from courtyard.common.client import HubClient, HubError
from courtyard.common.models import Message
from courtyard.puppet.core import Puppet, ScriptBehavior, ScriptStep


def make_puppet(hub: str, name: str, behavior) -> Puppet:
    admin = HubClient(hub)
    _, token = admin.register_agent(name, "puppet")
    admin.close()
    puppet = Puppet(hub, name, token, behavior, heartbeat_seconds=0.5)
    puppet.start()
    return puppet


def wait_for_messages(admin: HubClient, line_id, count: int, timeout: float = 10.0) -> list:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        messages = [m for m in admin.line_messages(line_id) if m.kind == "message"]
        if len(messages) >= count:
            return messages
        time.sleep(0.05)
    raise AssertionError(f"only {len(messages)}/{count} messages: {[m.body for m in messages]}")


def test_two_scripted_puppets_hold_a_full_conversation(live_hub):
    hub = live_hub()
    admin = HubClient(hub)
    alice = make_puppet(
        hub,
        "alice",
        ScriptBehavior(
            [
                ScriptStep(match="capacity", reply="great, deploying to staging then", delay=0.05),
                ScriptStep(match="rollout", reply="thanks, merging now", delay=0.05),
            ]
        ),
    )
    bob = make_puppet(
        hub,
        "bob",
        ScriptBehavior(
            [
                ScriptStep(match="deploy", reply="cluster has capacity, go ahead", delay=0.05),
                ScriptStep(match="staging", reply="rollout is green", delay=0.05),
            ]
        ),
    )

    opening = alice.say("bob", "can you deploy payments?")
    assert opening is not None and opening.status == "pending_gate"  # supervised holds
    time.sleep(0.3)
    assert bob.client.inbox() == []  # gate really holds: nothing reached bob

    admin.set_mode(opening.line_id, "auto_pass")  # future sends flow
    admin.decide(opening.id, "approve")  # ...and the opening is released

    messages = wait_for_messages(admin, opening.line_id, 5)
    assert [m.body for m in messages] == [
        "can you deploy payments?",
        "cluster has capacity, go ahead",
        "great, deploying to staging then",
        "rollout is green",
        "thanks, merging now",
    ]
    assert [m.sender_name for m in messages] == ["alice", "bob", "alice", "bob", "alice"]
    assert all(m.status == "delivered" for m in messages)
    # threading: a reply closes the exchange (line -> idle); the next send opens a new one
    assert messages[1].reply_to == messages[0].id
    assert messages[2].reply_to is None
    assert messages[3].reply_to == messages[2].id
    assert messages[4].reply_to is None

    alice.stop()
    bob.stop()
    admin.close()


def test_turn_violation_surfaces_as_a_machine_readable_error(live_hub):
    hub = live_hub()
    admin = HubClient(hub)
    _, alice_token = admin.register_agent("alice", "puppet")
    admin.register_agent("bob", "puppet")
    alice = HubClient(hub, "alice", alice_token)

    alice.send("bob", "first")
    with pytest.raises(HubError) as exc:
        alice.send("bob", "second before any reply")
    assert exc.value.code == "gate_pending"  # the supervised flavor of "wait your turn"

    admin.decide(admin.pending()[0].id, "approve")
    with pytest.raises(HubError) as exc:
        alice.send("bob", "second while awaiting reply")
    assert exc.value.code == "turn_violation"
    assert exc.value.http_status == 409
    alice.close()
    admin.close()


# -- script behavior unit tests (no hub) ---------------------------------------------


class StubPuppet:
    def __init__(self):
        self.said: list[tuple[str, str]] = []
        self.logs: list[str] = []

    def say(self, to, body):
        self.said.append((to, body))

    def log(self, text):
        self.logs.append(text)

    def show(self, m):
        pass


def fake_message(body: str, kind: str = "message", sender: str = "peer") -> Message:
    return Message(
        id=uuid4(),
        line_id=uuid4(),
        seq=1,
        sender=uuid4(),
        recipient=uuid4(),
        kind=kind,
        body=body,
        status="delivered",
        created_at=datetime.now(UTC),
        sender_name=sender,
    )


def test_script_steps_fire_once_in_order_and_match_case_insensitively():
    behavior = ScriptBehavior(
        [
            ScriptStep(match="Deploy", reply="ok", delay=0),
            ScriptStep(match=None, reply="fallback", delay=0),
        ]
    )
    stub = StubPuppet()
    behavior.on_message(fake_message("please DEPLOY this"), stub)
    behavior.on_message(fake_message("deploy again?"), stub)  # step 1 used; falls to step 2
    behavior.on_message(fake_message("anything"), stub)  # exhausted: silent
    assert stub.said == [("peer", "ok"), ("peer", "fallback")]
    assert any("no reply" in log for log in stub.logs)


def test_script_never_replies_to_notes_or_system_messages():
    behavior = ScriptBehavior([ScriptStep(match=None, reply="should not fire", delay=0)])
    stub = StubPuppet()
    behavior.on_message(fake_message("note", kind="operator_note"), stub)
    behavior.on_message(fake_message("notice", kind="system"), stub)
    assert stub.said == []
