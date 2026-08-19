"""Repository interfaces (design doc §9.1). The hub is the single writer; every mutating
service operation runs inside exactly one Storage.transaction()."""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Any, Protocol
from uuid import UUID

from courtyard.common.models import Agent, Line, Message


class AgentRepo(Protocol):
    def create(
        self,
        *,
        agent_id: UUID,
        name: str,
        type: str,
        description: str | None,
        workdir: str | None,
        token_hash: str,
        launch: dict[str, Any] | None,
    ) -> Agent: ...

    def get(self, agent_id: UUID) -> Agent | None: ...

    def get_by_name(self, name: str) -> Agent | None: ...

    def get_by_token_hash(self, token_hash: str) -> Agent | None: ...

    def list(self) -> list[Agent]: ...

    def set_status(self, agent_id: UUID, status: str) -> None: ...


class LineRepo(Protocol):
    def get_or_create_locked(self, a: UUID, b: UUID) -> Line:
        """Return the line for the (unordered) pair, row-locked; create it if missing."""
        ...

    def get(self, line_id: UUID) -> Line | None: ...

    def get_locked(self, line_id: UUID) -> Line | None: ...

    def list(self) -> list[Line]: ...

    def set_mode(self, line_id: UUID, mode: str) -> None: ...

    def set_turn(
        self, line_id: UUID, state: str, awaiting_from: UUID | None, in_flight_msg: UUID | None
    ) -> None: ...


class MessageRepo(Protocol):
    def insert(
        self,
        *,
        message_id: UUID,
        line_id: UUID,
        sender: UUID | None,
        recipient: UUID | None,
        kind: str,
        body: str,
        reply_to: UUID | None,
        status: str,
    ) -> Message:
        """Insert with the next per-line seq. Caller must hold the line row lock."""
        ...

    def get(self, message_id: UUID) -> Message | None: ...

    def list_line(self, line_id: UUID, after: int | None = None) -> list[Message]: ...

    def pending_gate(self) -> list[Message]: ...

    def take_queued_for(self, agent_id: UUID) -> list[Message]:
        """Return this agent's queued messages and mark them delivered (the pull path)."""
        ...

    def apply_gate(
        self, message_id: UUID, status: str, verdict: str, note: str | None, decided_by: UUID
    ) -> Message: ...


class UnitOfWork(Protocol):
    agents: AgentRepo
    lines: LineRepo
    messages: MessageRepo


class Storage(Protocol):
    def transaction(self) -> AbstractContextManager[UnitOfWork]: ...
