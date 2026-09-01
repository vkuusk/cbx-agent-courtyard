"""Items 33/34 (D29/D30): the channel-flag report and the delivery-verification check.

Live-hub tests with dummy receivers: the check rides the normal push payload, the
dummy reads the rendered envelope, extracts the token and acks it — the same round
trip a real model performs.
"""

from __future__ import annotations

import re
import time

from courtyard.common.client import ChannelReceiver, HubClient


def wait_for(predicate, timeout=5.0, what="condition"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.03)
    raise AssertionError(f"{what} never happened")


def agent_row(admin: HubClient, name: str):
    return next(a for a in admin.agents() if a.name == name)


def attach_dummy(hub, admin, name, flag="unknown"):
    _, token = admin.register_agent(name, "dummy")
    client = HubClient(hub, name, token)
    inbox = []
    receiver = ChannelReceiver(inbox.append)
    client.attach(receiver.endpoint, receiver.channel_token, flag)
    return client, receiver, inbox


def test_attach_stores_the_channel_flag(live_hub):
    hub = live_hub()
    admin = HubClient(hub)
    bob, receiver, _ = attach_dummy(hub, admin, "bob", flag="absent")
    assert agent_row(admin, "bob").channel_flag == "absent"
    # A restart with the proper launch command is a new attach: the report follows.
    bob.attach(receiver.endpoint, receiver.channel_token, "present")
    assert agent_row(admin, "bob").channel_flag == "present"
    receiver.stop()
    admin.close()
    bob.close()


def test_verify_delivery_round_trip(live_hub):
    hub = live_hub()
    admin = HubClient(hub)
    bob, receiver, inbox = attach_dummy(hub, admin, "bob")
    assert agent_row(admin, "bob").delivery_check is None  # no shift: no automatic check

    admin.verify_delivery("bob")
    check = wait_for(lambda: inbox and inbox[0], what="check push")
    assert check.kind == "system"
    assert "courtyard_ack" in check.rendered
    assert agent_row(admin, "bob").delivery_check == "pending"

    token = re.search(r'token "([^"]+)"', check.rendered).group(1)
    assert bob.ack(token) is True
    row = agent_row(admin, "bob")
    assert row.delivery_check == "verified" and row.delivery_checked_at is not None
    assert bob.ack(token) is False  # the check is closed; a late repeat is not an error
    assert admin.lines() == []  # the check never touches history

    receiver.stop()
    admin.close()
    bob.close()


def test_unacked_check_times_out_as_failed(live_hub):
    hub = live_hub(verify_timeout=0.2, sweep_seconds=0.05)
    admin = HubClient(hub)
    bob, receiver, inbox = attach_dummy(hub, admin, "bob")
    admin.verify_delivery("bob")
    wait_for(lambda: inbox, what="check push")
    wait_for(
        lambda: agent_row(admin, "bob").delivery_check == "failed",
        what="check timeout",
    )
    receiver.stop()
    admin.close()
    bob.close()


def test_attach_during_a_shift_triggers_a_check(live_hub):
    """Item 34: a session beginning while a shift is active is checked automatically —
    shift-start spawns, Resume respawns, manual mid-shift restarts, hub-restart
    re-attaches all reach this same attach path."""
    hub = live_hub()
    admin = HubClient(hub)
    admin._call("POST", "/api/shift/start")  # no launchable agents: state `starting`
    bob, receiver, inbox = attach_dummy(hub, admin, "bob")
    check = wait_for(lambda: inbox and inbox[0], what="automatic check push")
    assert "courtyard_ack" in check.rendered
    assert agent_row(admin, "bob").delivery_check == "pending"
    admin._call("POST", "/api/shift/end", {"force": True})
    receiver.stop()
    admin.close()
    bob.close()
