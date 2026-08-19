"""The pluggable approver seam (design doc §5.5, D10).

v1 ships only the human path: decisions arrive via the REST gate endpoint, so the hub-side
approver only needs to announce that something is pending. Step 2 wires this to SSE; a
future orchestrator-agent approver implements the same protocol.
"""

from __future__ import annotations

from typing import Protocol

from courtyard.common.models import Line, Message


class Approver(Protocol):
    def on_pending(self, line: Line, message: Message) -> None: ...


class NoopApprover:
    """Placeholder until the SSE stream exists (step 2)."""

    def on_pending(self, line: Line, message: Message) -> None:
        return None
