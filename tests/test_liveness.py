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
