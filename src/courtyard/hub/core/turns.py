"""The turn-taking state machine (design doc §5.4) as pure functions.

No I/O here. Services lock the line row, call these planners, then persist the plan in the
same transaction. The invariant: per line, at most one unanswered `message` in flight.
`operator_note` and `system` messages never pass through here — they are turn-exempt.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from courtyard.hub.core.errors import (
    CannotRelease,
    GatePendingBlock,
    NotPending,
    TurnViolation,
)


@dataclass(frozen=True)
class TurnState:
    """The turn-relevant slice of a line row."""

    mode: str  # supervised | auto_pass
    state: str  # idle | pending_gate | awaiting_reply
    awaiting_from: UUID | None
    in_flight_msg: UUID | None


@dataclass(frozen=True)
class SendPlan:
    message_status: str  # pending_gate | queued
    reply_to: UUID | None
    line_state: str
    awaiting_from: UUID | None
    track_new_message: bool  # True -> line.in_flight_msg becomes the new message's id


def plan_message_send(line: TurnState, sender: UUID, recipient: UUID) -> SendPlan:
    if line.state == "pending_gate":
        raise GatePendingBlock(
            "line blocked: a message is awaiting a gate decision",
            in_flight_msg=str(line.in_flight_msg),
        )
    reply_to = None
    if line.state == "awaiting_reply":
        if sender != line.awaiting_from:
            raise TurnViolation(
                "line busy: awaiting a reply to the message in flight; "
                "you may send again once it is answered",
                awaiting_from=str(line.awaiting_from),
                in_flight_msg=str(line.in_flight_msg),
            )
        reply_to = line.in_flight_msg
    if line.mode == "supervised":
        return SendPlan("pending_gate", reply_to, "pending_gate", None, True)
    if reply_to is not None:
        # auto-pass reply delivered -> exchange complete, line returns to idle
        return SendPlan("queued", reply_to, "idle", None, False)
    return SendPlan("queued", None, "awaiting_reply", recipient, True)


@dataclass(frozen=True)
class GatePlan:
    message_status: str  # queued | returned | rejected
    line_state: str
    awaiting_from: UUID | None
    in_flight_msg: UUID | None
    notify_sender: bool


def plan_gate_decision(
    line: TurnState,
    message_id: UUID,
    message_reply_to: UUID | None,
    message_recipient: UUID | None,
    verdict: str,
) -> GatePlan:
    if line.state != "pending_gate" or line.in_flight_msg != message_id:
        raise NotPending("message is not awaiting a gate decision")
    if verdict == "approve":
        if message_reply_to is not None:
            return GatePlan("queued", "idle", None, None, False)
        return GatePlan("queued", "awaiting_reply", message_recipient, message_id, False)
    if verdict == "return":
        return GatePlan("returned", "idle", None, None, True)
    return GatePlan("rejected", "idle", None, None, True)


def plan_release(line: TurnState) -> None:
    """Validate that a stuck line may be released back to idle (raises otherwise)."""
    if line.state == "pending_gate":
        raise CannotRelease(
            "decide the pending gate message first",
            in_flight_msg=str(line.in_flight_msg),
        )
    if line.state == "idle":
        raise CannotRelease("line is already idle")
