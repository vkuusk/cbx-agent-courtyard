"""Board operations: send, gate decisions, notes, release, reads.

Every mutation is exactly one transaction that locks the line row, runs the pure turn
machine, and persists the plan — the message write and the line-state transition can never
be observed apart (design doc §6.1, §9.2).
"""

from __future__ import annotations

from uuid import UUID, uuid4

from courtyard.common.models import Agent, Line, Message
from courtyard.hub.core import turns
from courtyard.hub.core.deliver import Deliverer
from courtyard.hub.core.errors import (
    AgentGone,
    BodyTooLarge,
    InvalidRecipient,
    LineNotFound,
    MessageNotFound,
)
from courtyard.hub.core.events import EventBus
from courtyard.hub.core.gate import Approver
from courtyard.hub.core.registry import OPERATOR_NAME, Registry
from courtyard.hub.storage.repo import Storage, UnitOfWork


def _turn_state(line: Line) -> turns.TurnState:
    return turns.TurnState(line.mode, line.state, line.awaiting_from, line.in_flight_msg)


class Board:
    def __init__(
        self,
        storage: Storage,
        registry: Registry,
        approver: Approver,
        max_body_bytes: int,
        events: EventBus,
        deliverer: Deliverer,
    ):
        self._storage = storage
        self._registry = registry
        self._approver = approver
        self._max_body_bytes = max_body_bytes
        self._events = events
        self._deliverer = deliverer

    # -- sending -------------------------------------------------------------------

    def send(self, sender: Agent, to: str, body: str) -> Message:
        """A turn-taking `message` from an authenticated agent (or the operator)."""
        self._check_body(body)
        with self._storage.transaction() as uow:
            recipient = self._registry.resolve(uow, to)
            if recipient.id == sender.id:
                raise InvalidRecipient("cannot send a message to yourself")
            if recipient.removed_at is not None:
                raise AgentGone(f"agent {recipient.name!r} was removed from the courtyard")
            line = uow.lines.get_or_create_locked(sender.id, recipient.id)
            plan = turns.plan_message_send(_turn_state(line), sender.id, recipient.id)
            message = uow.messages.insert(
                message_id=uuid4(),
                line_id=line.id,
                sender=sender.id,
                recipient=recipient.id,
                kind="message",
                body=body,
                reply_to=plan.reply_to,
                status=plan.message_status,
            )
            uow.lines.set_turn(
                line.id,
                plan.line_state,
                plan.awaiting_from,
                message.id if plan.track_new_message else None,
            )
            line = uow.lines.get(line.id)
        self._events.publish("message", message)
        self._events.publish("line", line)
        if message.status == "pending_gate":
            self._approver.on_pending(line, message)
        elif message.status == "queued":
            message = self._deliverer.deliver(message)
        return message

    def note(self, line_id: UUID, target: str, body: str) -> Message:
        """Operator insertion into a line, targeted at one participant. Turn-exempt."""
        self._check_body(body)
        with self._storage.transaction() as uow:
            line = uow.lines.get_locked(line_id)
            if line is None:
                raise LineNotFound("no such line")
            operator = uow.agents.get_by_name(OPERATOR_NAME)
            recipient = self._registry.resolve(uow, target)
            if recipient.id not in (line.agent_a, line.agent_b):
                raise InvalidRecipient(
                    f"agent {recipient.name!r} is not a participant of this line"
                )
            message = uow.messages.insert(
                message_id=uuid4(),
                line_id=line.id,
                sender=operator.id,
                recipient=recipient.id,
                kind="operator_note",
                body=body,
                reply_to=None,
                status="queued",
            )
        self._events.publish("message", message)
        return self._deliverer.deliver(message)

    # -- the gate ------------------------------------------------------------------

    def decide(self, message_id: UUID, verdict: str, note: str | None) -> Message:
        notice = None
        with self._storage.transaction() as uow:
            message = uow.messages.get(message_id)
            if message is None:
                raise MessageNotFound("no such message")
            line = uow.lines.get_locked(message.line_id)
            plan = turns.plan_gate_decision(
                _turn_state(line), message.id, message.reply_to, message.recipient, verdict
            )
            operator = uow.agents.get_by_name(OPERATOR_NAME)
            updated = uow.messages.apply_gate(
                message.id, plan.message_status, verdict, note, operator.id
            )
            uow.lines.set_turn(line.id, plan.line_state, plan.awaiting_from, plan.in_flight_msg)
            if plan.notify_sender and message.sender is not None:
                notice = self._notify_sender(uow, updated, verdict, note)
            line = uow.lines.get(line.id)
        self._events.publish("message", updated)
        self._events.publish("line", line)
        if updated.status == "queued":  # approved: now actually deliver it
            updated = self._deliverer.deliver(updated)
        if notice is not None:
            self._events.publish("message", notice)
            self._deliverer.deliver(notice)
        return updated

    def _notify_sender(
        self, uow: UnitOfWork, message: Message, verdict: str, note: str | None
    ) -> Message:
        verb = "returned to you for revision" if verdict == "return" else "rejected (do not resend)"
        body = f"Your message (seq {message.seq}) to {message.recipient_name} was {verb}."
        if note:
            body += f" Gate comment: {note}"
        return uow.messages.insert(
            message_id=uuid4(),
            line_id=message.line_id,
            sender=None,
            recipient=message.sender,
            kind="system",
            body=body,
            reply_to=message.id,
            status="queued",
        )

    def pending(self) -> list[Message]:
        with self._storage.transaction() as uow:
            return uow.messages.pending_gate()

    # -- line administration -------------------------------------------------------

    def set_mode(self, line_id: UUID, mode: str) -> Line:
        """Flip the supervision dial. Affects future sends only: a message already
        pending at the gate still needs its decision."""
        with self._storage.transaction() as uow:
            if uow.lines.get_locked(line_id) is None:
                raise LineNotFound("no such line")
            uow.lines.set_mode(line_id, mode)
            line = uow.lines.get(line_id)
        self._events.publish("line", line)
        return line

    def release(self, line_id: UUID) -> Line:
        """Operator escape valve for a line stuck awaiting a reply (design doc §5.4)."""
        with self._storage.transaction() as uow:
            line = uow.lines.get_locked(line_id)
            if line is None:
                raise LineNotFound("no such line")
            turns.plan_release(_turn_state(line))
            uow.lines.set_turn(line.id, "idle", None, None)
            entry = uow.messages.insert(
                message_id=uuid4(),
                line_id=line.id,
                sender=None,
                recipient=None,  # log-only board entry
                kind="system",
                body="line released to idle by the operator",
                reply_to=line.in_flight_msg,
                status="delivered",
            )
            line = uow.lines.get(line.id)
        self._events.publish("message", entry)
        self._events.publish("line", line)
        return line

    # -- reads ---------------------------------------------------------------------

    def lines(self) -> list[Line]:
        with self._storage.transaction() as uow:
            return uow.lines.list()

    def line(self, line_id: UUID) -> Line:
        with self._storage.transaction() as uow:
            line = uow.lines.get(line_id)
        if line is None:
            raise LineNotFound("no such line")
        return line

    def line_messages(self, line_id: UUID, after: int | None = None) -> list[Message]:
        with self._storage.transaction() as uow:
            if uow.lines.get(line_id) is None:
                raise LineNotFound("no such line")
            return uow.messages.list_line(line_id, after)

    def inbox(self, agent: Agent) -> list[Message]:
        with self._storage.transaction() as uow:
            return uow.messages.take_queued_for(agent.id)

    # -- helpers -------------------------------------------------------------------

    def _check_body(self, body: str) -> None:
        if len(body.encode()) > self._max_body_bytes:
            raise BodyTooLarge(f"message body exceeds {self._max_body_bytes} bytes")
