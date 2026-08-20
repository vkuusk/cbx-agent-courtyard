"""The SSE stream: board changes arrive as typed events with full objects."""

from __future__ import annotations

import json
import threading
import time

import httpx

from courtyard.common.client import HubClient


class EventTap:
    """Collects (type, data) pairs from /api/events on a background thread."""

    def __init__(self, hub_url: str):
        self.events: list[tuple[str, dict]] = []
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(hub_url,), daemon=True)
        self._thread.start()
        assert self._ready.wait(5), "SSE stream never opened"

    def _run(self, hub_url: str) -> None:
        with httpx.stream("GET", f"{hub_url}/api/events", timeout=30) as resp:
            event_type = None
            for line in resp.iter_lines():
                if line == ": connected":
                    self._ready.set()
                elif line.startswith("event:"):
                    event_type = line.removeprefix("event:").strip()
                elif line.startswith("data:") and event_type:
                    self.events.append((event_type, json.loads(line.removeprefix("data:"))))
                    event_type = None

    def wait_for(self, event_type: str, timeout: float = 5.0) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for t, data in self.events:
                if t == event_type:
                    return data
            time.sleep(0.02)
        raise AssertionError(f"no {event_type!r} event; saw {[t for t, _ in self.events]}")


def test_board_changes_stream_as_events(live_hub):
    hub = live_hub()
    admin = HubClient(hub)
    tap = EventTap(hub)

    _, alice_token = admin.register_agent("alice", "puppet")
    admin.register_agent("bob", "puppet")
    assert tap.wait_for("agent")["name"] == "alice"

    alice = HubClient(hub, "alice", alice_token)
    sent = alice.send("bob", "hello")
    assert tap.wait_for("message")["body"] == "hello"
    assert tap.wait_for("line")["state"] == "pending_gate"
    assert tap.wait_for("gate")["id"] == str(sent.id)  # the approver's announcement

    admin.decide(sent.id, "reject", "not like this")
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        rejected = [d for t, d in tap.events if t == "message" and d["status"] == "rejected"]
        notices = [d for t, d in tap.events if t == "message" and d["kind"] == "system"]
        if rejected and notices:
            break
        time.sleep(0.02)
    assert rejected and rejected[0]["id"] == str(sent.id)
    assert "rejected" in notices[0]["body"]
    alice.close()
    admin.close()
