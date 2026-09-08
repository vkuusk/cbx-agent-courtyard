"""Board operations: send, gate decisions, notes, release, reads.

Every mutation is exactly one transaction that locks the line row, runs the pure turn
machine, and persists the plan — the message write and the line-state transition can never
be observed apart (design doc §6.1, §9.2).
"""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID, uuid4

from courtyard.common.models import Agent, Line, Message, Thread
from courtyard.hub.core import turns
from courtyard.hub.core.deliver import Deliverer
from courtyard.hub.core.envelope import with_rendering
from courtyard.hub.core.errors import (
    AgentGone,
    AlreadyLinked,
    BodyTooLarge,
    GatePendingBlock,
    InvalidRecipient,
    LineNotFound,
    MessageNotFound,
    NoOpenThread,
    NotAllowed,
    NotLinked,
    NotThreadInitiator,
    ThreadStillOpen,
)
from courtyard.hub.core.events import EventBus
from courtyard.hub.core.gate import Approver
from courtyard.hub.core.registry import OPERATOR_NAME, Registry
from courtyard.hub.storage.repo import Storage, UnitOfWork


def _turn_state(line: Line) -> turns.TurnState:
    return turns.TurnState(line.mode, line.state, line.awaiting_from, line.in_flight_msg)


def expire_open_work(uow: UnitOfWork) -> tuple[list[Line], list[Message], list[Thread]]:
    """End-of-shift close-out (design §8.1, D24; §D34): every non-idle line goes back to
    idle and its unfinished message — awaiting a reply (queued or delivered) or held at
    the gate — becomes `expired`, with a `system` entry in the line's history; every
    open thread becomes `expired` too, the same close-out at task granularity. Nothing
    is deleted, nothing is delivered; the record is the point. Bypasses the turn
    planners deliberately, like `release`: an administrative transition, not a turn.

    Returns (changed lines, messages to publish, expired threads) for the caller's
    event fan-out.
    """
    touched: set[UUID] = set()
    publish: list[Message] = []
    for line in uow.lines.list():
        if line.state == "idle":
            continue
        locked = uow.lines.get_locked(line.id)
        if locked is None or locked.state == "idle":
            continue  # answered or released between the list and the lock
        expired = None
        if locked.in_flight_msg is not None:
            expired = uow.messages.expire(locked.in_flight_msg)
        uow.lines.set_turn(locked.id, "idle", None, None)
        what = "held at the gate" if locked.state == "pending_gate" else "awaiting a reply"
        entry = uow.messages.insert(
            message_id=uuid4(),
            line_id=locked.id,
            sender=None,
            recipient=None,  # log-only board entry
            kind="system",
            body=f"the message {what} expired at end of shift",
            reply_to=locked.in_flight_msg,
            status="delivered",
            thread_id=locked.open_thread,
        )
        if expired is not None:
            publish.append(expired)
        publish.append(entry)
        touched.add(locked.id)
    # D34: threads outlive turns, so an idle line can still hold an open thread —
    # every one of them ends here, whatever its line was doing.
    expired_threads = uow.threads.expire_open()
    for thread in expired_threads:
        uow.lines.get_locked(thread.line_id)  # insert bumps the per-line seq
        uow.lines.set_open_thread(thread.line_id, None)
        publish.append(
            uow.messages.insert(
                message_id=uuid4(),
                line_id=thread.line_id,
                sender=None,
                recipient=None,  # log-only board entry
                kind="system",
                body="the open thread expired at end of shift",
                reply_to=None,
                status="delivered",
                thread_id=thread.id,
            )
        )
        touched.add(thread.line_id)
    return [uow.lines.get(line_id) for line_id in touched], publish, expired_threads


class Board:
    def __init__(
        self,
        storage: Storage,
        registry: Registry,
        approver: Approver,
        max_body_bytes: int,
        events: EventBus,
        deliverer: Deliverer,
        default_line_mode: Callable[[], str] | None = None,
        discovery: Callable[[], str] | None = None,
    ):
        self._storage = storage
        self._registry = registry
        self._approver = approver
        self._max_body_bytes = max_body_bytes
        self._events = events
        self._deliverer = deliverer
        # 7c: what supervision dial a NEW line starts on (the operator's Admin default).
        self._default_line_mode = default_line_mode or (lambda: "supervised")
        # §5.8 (D22): under manual discovery an agent-agent send needs an existing line.
        self._discovery = discovery or (lambda: "auto")

    # -- sending -------------------------------------------------------------------

    def send(self, sender: Agent, to: str, body: str, new_thread: bool = False) -> Message:
        """A turn-taking `message` from an authenticated agent (or the operator).

        `new_thread` is the sender's boundary declaration (D34): under serial v1 its one
        job is to be refused while the line's thread is still open — a message on a line
        with no open thread opens one whether declared or not, and any other message
        continues the open thread.
        """
        self._check_body(body)
        opened = None
        with self._storage.transaction() as uow:
            recipient = self._registry.resolve(uow, to)
            if recipient.id == sender.id:
                raise InvalidRecipient("cannot send a message to yourself")
            if recipient.removed_at is not None:
                raise AgentGone(f"agent {recipient.name!r} was removed from the courtyard")
            if self._discovery() == "manual" and "human" not in (sender.type, recipient.type):
                # §5.8 (D22): the line IS the permission — no line, no send. Operator
                # pairs are exempt and keep forming their line on first message below.
                line = uow.lines.get_pair_locked(sender.id, recipient.id)
                if line is None:
                    raise NotLinked(
                        f"you have no line with {recipient.name!r}; "
                        "the operator links agents in this courtyard"
                    )
            else:
                line = uow.lines.get_or_create_locked(
                    sender.id, recipient.id, self._default_line_mode()
                )
            if "human" in (sender.type, recipient.type) and line.mode != "auto_pass":
                # Operator lines are never gated (design §5.6, D9). Enforced here so the
                # invariant holds however the line was created or later toggled.
                uow.lines.set_mode(line.id, "auto_pass")
                line = uow.lines.get_locked(line.id)
            plan = turns.plan_message_send(_turn_state(line), sender.id, recipient.id)
            thread_id = line.open_thread
            if thread_id is None:
                # The first message of a new exchange opens the thread — declared or
                # not, it is the only possibility on a line with none (D34).
                opened = uow.threads.insert(thread_id=uuid4(), line_id=line.id, opened_by=sender.id)
                uow.lines.set_open_thread(line.id, opened.id)
                thread_id = opened.id
            elif new_thread:
                thread = uow.threads.get(thread_id)
                raise ThreadStillOpen(
                    f"a thread is still open on your line with {recipient.name!r}; a new "
                    "ask begins only after it is closed. Send without new_thread to "
                    "continue the open thread, or — if you opened it and the ask is "
                    "settled — close it first",
                    opened_by=thread.opened_by_name or str(thread.opened_by),
                )
            message = uow.messages.insert(
                message_id=uuid4(),
                line_id=line.id,
                sender=sender.id,
                recipient=recipient.id,
                kind="message",
                body=body,
                reply_to=plan.reply_to,
                status=plan.message_status,
                thread_id=thread_id,
            )
            uow.lines.set_turn(
                line.id,
                plan.line_state,
                plan.awaiting_from,
                message.id if plan.track_new_message else None,
            )
            line = uow.lines.get(line.id)
        if opened is not None:
            self._events.publish("thread", opened)
        self._events.publish("message", message)
        self._events.publish("line", line)
        if message.status == "pending_gate":
            self._approver.on_pending(line, message)
        elif message.status == "queued":
            message = self._deliverer.deliver(message)
        return message

    def close_thread(self, closer: Agent, with_: str) -> Thread:
        """Close the open thread on the closer's line with a peer (D34): the initiator
        declares the ask settled. A dedicated protocol event with no message and no
        note — the peer learns of it from a fixed system line. Closing resolves the
        line's reply obligation, so a closed thread never leaves a line stuck."""
        with self._storage.transaction() as uow:
            peer = self._registry.resolve(uow, with_)
            if peer.id == closer.id:
                raise InvalidRecipient("you have no line with yourself")
            line = uow.lines.get_pair_locked(closer.id, peer.id)
            if line is None or line.open_thread is None:
                raise NoOpenThread(f"no open thread on your line with {peer.name!r}")
            thread = uow.threads.get(line.open_thread)
            if thread.opened_by != closer.id:
                raise NotThreadInitiator(
                    f"this thread was opened by {thread.opened_by_name!r}; only its "
                    "initiator closes it — answer with a message instead",
                )
            if line.state == "pending_gate":
                raise GatePendingBlock(
                    "a message on this line is awaiting the operator's gate decision; "
                    "the thread cannot close until it is decided",
                    in_flight_msg=str(line.in_flight_msg),
                )
            thread = uow.threads.end(thread.id, "closed")
            uow.lines.set_open_thread(line.id, None)
            if line.state == "awaiting_reply":
                # The close resolves the reply obligation, whichever side owed it.
                uow.lines.set_turn(line.id, "idle", None, None)
            entry = uow.messages.insert(
                message_id=uuid4(),
                line_id=line.id,
                sender=None,
                recipient=peer.id,
                kind="system",
                body=f"thread closed by {closer.name}",
                reply_to=None,
                status="queued",
                thread_id=thread.id,
            )
            line = uow.lines.get(line.id)
        self._events.publish("thread", thread)
        self._events.publish("message", entry)
        self._events.publish("line", line)
        self._deliverer.deliver(entry)
        return thread

    def line_threads(self, line_id: UUID) -> list[Thread]:
        with self._storage.transaction() as uow:
            if uow.lines.get(line_id) is None:
                raise LineNotFound("no such line")
            return uow.threads.list_line(line_id)

    def note(self, line_id: UUID, target: str, body: str) -> list[Message]:
        """Operator insertion into an inter-agent line, targeted at one participant or
        "both" (design §5.6). Turn-exempt; delivered immediately."""
        self._check_body(body)
        with self._storage.transaction() as uow:
            line = uow.lines.get_locked(line_id)
            if line is None:
                raise LineNotFound("no such line")
            operator = uow.agents.get_by_name(OPERATOR_NAME)
            if operator.id in (line.agent_a, line.agent_b):
                raise NotAllowed(
                    "this is one of the operator's own lines — send a message, not a note"
                )
            if target == "both":
                recipients = [uow.agents.get(line.agent_a), uow.agents.get(line.agent_b)]
            else:
                recipient = self._registry.resolve(uow, target)
                if recipient.id not in (line.agent_a, line.agent_b):
                    raise InvalidRecipient(
                        f"agent {recipient.name!r} is not a participant of this line"
                    )
                recipients = [recipient]
            notes = [
                uow.messages.insert(
                    message_id=uuid4(),
                    line_id=line.id,
                    sender=operator.id,
                    recipient=recipient.id,
                    kind="operator_note",
                    body=body,
                    reply_to=None,
                    status="queued",
                    thread_id=line.open_thread,  # commentary rides the open exchange, if any
                )
                for recipient in recipients
            ]
        for note in notes:
            self._events.publish("message", note)
        return [self._deliverer.deliver(note) for note in notes]

    def inbox_history(self, agent: Agent, limit: int = 50) -> list[Message]:
        """Messages addressed to this agent, newest first — the operator's inbox read
        (non-consuming: human-recipient messages are already delivered, §6.1)."""
        with self._storage.transaction() as uow:
            return uow.messages.list_for_recipient(agent.id, limit)

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
                # Item 24 (c): only a return carries the comment back — a drop sends the
                # operator's comment nowhere (the notice itself still ends the exchange).
                notice = self._notify_sender(
                    uow, updated, verdict, note if verdict == "return" else None
                )
            elif verdict == "approve" and note:
                # An approve note rides along to the recipient as an operator note —
                # "add, not edit" (D7): the message passes untouched, the comment is its own.
                notice = uow.messages.insert(
                    message_id=uuid4(),
                    line_id=message.line_id,
                    sender=operator.id,
                    recipient=message.recipient,
                    kind="operator_note",
                    body=note,
                    reply_to=message.id,
                    status="queued",
                    thread_id=message.thread_id,
                )
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
        verb = "returned to you for revision" if verdict == "return" else "dropped (do not resend)"
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
            thread_id=message.thread_id,
        )

    def pending(self) -> list[Message]:
        with self._storage.transaction() as uow:
            return uow.messages.pending_gate()

    # -- line administration -------------------------------------------------------

    def link(self, a: str, b: str, mode: str | None = None) -> Line:
        """Operator gesture (§5.8, D22): pre-create the idle line between two agents —
        under manual discovery that line is what lets them reach each other. Harmless
        under auto (the line would have formed on first message anyway). `mode` (used
        by charter projection, D33) overrides the Admin default for the new line."""
        with self._storage.transaction() as uow:
            agents = (self._registry.resolve(uow, a), self._registry.resolve(uow, b))
            if agents[0].id == agents[1].id:
                raise InvalidRecipient("cannot link an agent to itself")
            for agent in agents:
                if agent.removed_at is not None:
                    raise AgentGone(f"agent {agent.name!r} was removed from the courtyard")
                if agent.type == "human":
                    raise NotAllowed(
                        "the operator needs no links — operator lines form on first message"
                    )
            if uow.lines.get_pair_locked(agents[0].id, agents[1].id) is not None:
                raise AlreadyLinked(f"{agents[0].name} and {agents[1].name} already have a line")
            line = uow.lines.get_or_create_locked(
                agents[0].id, agents[1].id, mode or self._default_line_mode()
            )
            line = uow.lines.get(line.id)
        self._events.publish("line", line)
        return line

    def set_mode(self, line_id: UUID, mode: str) -> Line:
        """Flip the supervision dial. Affects future sends only: a message already
        pending at the gate still needs its decision."""
        with self._storage.transaction() as uow:
            line = uow.lines.get_locked(line_id)
            if line is None:
                raise LineNotFound("no such line")
            participants = (uow.agents.get(line.agent_a), uow.agents.get(line.agent_b))
            if any(p.type == "human" for p in participants):
                raise NotAllowed("operator lines are never gated (design §5.6)")
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
                thread_id=line.open_thread,
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
        """The pull path: take the agent's queued messages (queued -> delivered, one
        transaction) and hand them over rendered, exactly as a push would (D14)."""
        with self._storage.transaction() as uow:
            taken = uow.messages.take_queued_for(agent.id)
            lines = {m.line_id: uow.lines.get(m.line_id) for m in taken}
        for message in taken:
            self._events.publish("message", message)
        for line in lines.values():
            self._events.publish("line", line)  # queued counters changed
        return [with_rendering(m) for m in taken]

    # -- helpers -------------------------------------------------------------------

    def _check_body(self, body: str) -> None:
        if len(body.encode()) > self._max_body_bytes:
            raise BodyTooLarge(f"message body exceeds {self._max_body_bytes} bytes")
