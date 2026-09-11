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
        try:
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
        except httpx.HTTPError:
            # the test hub closed the stream at teardown (its graceful-shutdown timeout):
            # the end of the stream, nothing to report from a background thread
            pass

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

    _, alice_token = admin.register_agent("alice", "dummy")
    admin.register_agent("bob", "dummy")
    assert tap.wait_for("agent")["name"] == "alice"

    alice = HubClient(hub, "alice", alice_token)
    sent = alice.send("bob", "hello")
    assert tap.wait_for("message")["body"] == "hello"
    assert tap.wait_for("line")["state"] == "pending_gate"
    assert tap.wait_for("gate")["id"] == str(sent.id)  # the approver's announcement

    admin.decide(sent.id, "drop", "not like this")
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        dropped = [d for t, d in tap.events if t == "message" and d["status"] == "dropped"]
        notices = [d for t, d in tap.events if t == "message" and d["kind"] == "system"]
        if dropped and notices:
            break
        time.sleep(0.02)
    assert dropped and dropped[0]["id"] == str(sent.id)
    assert "dropped" in notices[0]["body"]
    alice.close()
    admin.close()


def test_a_view_shapes_every_event_of_its_type_whoever_publishes():
    """State the hub keeps beside the stored row (an agent's rejected-token note) must
    reach the WebUI on every agent event, not only the registry's own: the store keeps
    the last event's object as the whole truth, so an event from the liveness sweep
    without the note wiped it from the card (found by review of the feedback-06 branch)."""
    import asyncio

    from pydantic import BaseModel

    from courtyard.hub.core.events import EventBus

    class Thing(BaseModel):
        name: str
        note: str | None = None

    bus = EventBus()
    loop = asyncio.new_event_loop()
    bus.bind(loop)
    queue = bus.subscribe()
    bus.view("thing", lambda m: m.model_copy(update={"note": "rejected"}))
    bus.publish("thing", Thing(name="a"))
    bus.publish("other", Thing(name="b"))
    loop.run_until_complete(asyncio.sleep(0))
    assert queue.get_nowait()["data"] == {"name": "a", "note": "rejected"}
    assert queue.get_nowait()["data"] == {"name": "b", "note": None}
    loop.close()
