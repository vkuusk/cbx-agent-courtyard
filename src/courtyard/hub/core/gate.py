"""The pluggable approver seam (design doc §5.5, D10).

v1 ships only the human path: decisions arrive via the REST gate endpoint, so the hub-side
approver only needs to announce that something is pending — as a `gate` SSE event the
WebUI (step 4) turns into its "something awaits you" indicator. A future
orchestrator-agent approver implements the same protocol.
"""

from __future__ import annotations

from typing import Protocol

from courtyard.common.models import Line, Message
from courtyard.hub.core.events import EventBus


class Approver(Protocol):
    def on_pending(self, line: Line, message: Message) -> None: ...


class EventApprover:
    """The human path: announce the pending message on the event stream and wait for
    the operator's REST verdict."""

    def __init__(self, events: EventBus):
        self._events = events

    def on_pending(self, line: Line, message: Message) -> None:
        self._events.publish("gate", message)


class NoopApprover:
    """For tests and scripts that need no announcements."""

    def on_pending(self, line: Line, message: Message) -> None:
        return None
