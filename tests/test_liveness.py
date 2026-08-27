"""Liveness decay: connected -> stale (3 missed beats) -> gone (window), advisory only,
and a returning heartbeat revives. Runs a hub with sub-second timings."""

from __future__ import annotations

import time

from courtyard.common.client import ChannelReceiver, HubClient


def wait_status(admin: HubClient, name: str, status: str, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        agent = next(a for a in admin.agents() if a.name == name)
        if agent.status == status:
            return
        time.sleep(0.03)
    raise AssertionError(f"{name} never became {status} (is {agent.status})")


def test_missed_heartbeats_decay_and_a_beat_revives(live_hub):
    hub = live_hub(heartbeat_seconds=0.1, gone_seconds=1.2, sweep_seconds=0.05)
    admin = HubClient(hub)
    _, token = admin.register_agent("bob", "puppet")
    bob = HubClient(hub, "bob", token)
    receiver = ChannelReceiver(lambda m: None)
    bob.attach(receiver.endpoint, receiver.channel_token)

    wait_status(admin, "bob", "connected", timeout=1.0)
    wait_status(admin, "bob", "stale")  # > 0.3s without a beat
    beat = bob.heartbeat()
    assert beat["status"] == "connected"
    wait_status(admin, "bob", "connected", timeout=1.0)

    wait_status(admin, "bob", "stale")
    wait_status(admin, "bob", "gone")  # > 1.2s without a beat

    assert bob.heartbeat()["status"] == "connected"  # gone by liveness is still re-attachable
    wait_status(admin, "bob", "connected", timeout=1.0)
    receiver.stop()
    admin.close()
    bob.close()


def test_restart_marks_stored_liveness_unknown_then_verifies(live_hub):
    """D26: a new hub never repeats a previous life's `connected`. Stored statuses flip
    to `unknown` at startup; a heartbeat proves an agent live immediately, and the sweep
    resolves the rest once the hub is past one heartbeat window (+5 s margin)."""
    hub1 = live_hub(heartbeat_seconds=0.1, gone_seconds=0.6, sweep_seconds=0.05)
    admin1 = HubClient(hub1)
    _, bob_token = admin1.register_agent("bob", "puppet")
    _, carol_token = admin1.register_agent("carol", "puppet")
    receiver = ChannelReceiver(lambda m: None)
    for name, token in (("bob", bob_token), ("carol", carol_token)):
        HubClient(hub1, name, token).attach(receiver.endpoint, receiver.channel_token)
    wait_status(admin1, "bob", "connected", timeout=1.0)
    wait_status(admin1, "carol", "connected", timeout=1.0)

    # "The next morning": a second hub over the same database.
    hub2 = live_hub(heartbeat_seconds=0.1, gone_seconds=0.6, sweep_seconds=0.05)
    admin2 = HubClient(hub2)
    wait_status(admin2, "bob", "unknown", timeout=2.0)
    wait_status(admin2, "carol", "unknown", timeout=2.0)

    # A heartbeat is proof and wins immediately, well inside the judging grace.
    bob2 = HubClient(hub2, "bob", bob_token)
    assert bob2.heartbeat()["status"] == "connected"
    wait_status(admin2, "bob", "connected", timeout=1.0)

    # carol never beats: the sweep resolves her to her true state after the grace
    # (heartbeat 0.1 + margin 5 s), in one pass — never back to a false green.
    wait_status(admin2, "carol", "gone", timeout=8.0)

    receiver.stop()
    for client in (admin1, admin2, bob2):
        client.close()
