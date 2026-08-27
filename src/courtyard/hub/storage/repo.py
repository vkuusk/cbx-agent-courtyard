"""Repository interfaces (design doc §9.1). The hub is the single writer; every mutating
service operation runs inside exactly one Storage.transaction()."""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Any, Protocol
from uuid import UUID

from courtyard.common.models import Agent, Archive, Channel, Line, Message


class AgentRepo(Protocol):
    def create(
        self,
        *,
        agent_id: UUID,
        name: str,
        type: str,
        description: str | None,
        sme_domain: str | None,
        workdir: str | None,
        token_hash: str,
        token: str,
        launch: dict[str, Any] | None,
        color: str | None,
        model: str | None,
    ) -> Agent: ...

    def get(self, agent_id: UUID) -> Agent | None: ...

    def update(self, agent_id: UUID, fields: dict) -> None:
        """Set the operator-editable columns (WP-D): description, sme_domain, workdir,
        model, color. None values clear. Caller validates which keys are allowed."""
        ...

    def get_token(self, agent_id: UUID) -> str | None:
        """The stored plaintext token (D19); None for registrations that predate storing it."""
        ...

    def set_token(self, agent_id: UUID, token_hash: str, token: str) -> None:
        """Rotate: replace both the lookup hash and the stored plaintext."""
        ...

    def get_by_name(self, name: str) -> Agent | None: ...

    def get_by_token_hash(self, token_hash: str) -> Agent | None: ...

    def list(self) -> list[Agent]: ...

    def set_status(self, agent_id: UUID, status: str) -> None: ...

    def touch(self, agent_id: UUID) -> None:
        """Update last_seen_at (attach / heartbeat)."""
        ...

    def mark_removed(self, agent_id: UUID) -> None: ...


class LineRepo(Protocol):
    def get_or_create_locked(self, a: UUID, b: UUID, mode: str = "supervised") -> Line:
        """Return the line for the (unordered) pair, row-locked; create it if missing.
        `mode` applies only on creation (7c: the operator's Admin default); an existing
        line keeps its own dial."""
        ...

    def get(self, line_id: UUID) -> Line | None: ...

    def get_locked(self, line_id: UUID) -> Line | None: ...

    def list(self) -> list[Line]: ...

    def list_for_agent(self, agent_id: UUID) -> list[Line]: ...

    def set_mode(self, line_id: UUID, mode: str) -> None: ...

    def set_turn(
        self, line_id: UUID, state: str, awaiting_from: UUID | None, in_flight_msg: UUID | None
    ) -> None: ...

    def delete(self, line_id: UUID) -> None:
        """Remove the line row (its messages must already be gone — archive first)."""
        ...


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

    def list_queued_for(self, agent_id: UUID) -> list[Message]:
        """The agent's queued backlog, oldest first, without consuming it (the push path)."""
        ...

    def count_queued_for(self, agent_id: UUID) -> int: ...

    def expire(self, message_id: UUID) -> Message | None:
        """Close an unfinished message as `expired` (D24, end of shift). Only a message
        still open — pending_gate, queued, or delivered — is touched; returns None
        otherwise. Caller must hold the line row lock."""
        ...

    def rearm_undischarged(self, agent_id: UUID) -> list[Message]:
        """R1 (D24, §6.4): flip this agent's delivered-but-unanswered in-flight messages
        back to `queued` so the attach backlog re-pushes them into the new session.
        Returns the re-armed messages (empty when there is nothing to re-arm)."""
        ...

    def list_for_recipient(self, agent_id: UUID, limit: int) -> list[Message]:
        """Messages addressed to the agent, any status, newest first (inbox history)."""
        ...

    def mark_delivered(self, message_id: UUID) -> Message | None:
        """queued -> delivered; None if the message was not queued (e.g. pull got it first)."""
        ...

    def apply_gate(
        self, message_id: UUID, status: str, verdict: str, note: str | None, decided_by: UUID
    ) -> Message: ...

    def delete_line(self, line_id: UUID) -> int:
        """Delete every message of a line (after it was archived). Returns the count."""
        ...


class ArchiveRepo(Protocol):
    def insert(
        self,
        *,
        archive_id: UUID,
        line_id: UUID,
        agent_a: UUID,
        agent_b: UUID,
        agent_a_name: str,
        agent_b_name: str,
        mode: str,
        reason: str,
        first_at: Any,
        last_at: Any,
        transcript: list[dict],
    ) -> Archive:
        """Store one archive document; returns the summary (no transcript)."""
        ...

    def list(self) -> list[Archive]:
        """Newest first, without transcripts."""
        ...

    def get(self, archive_id: UUID) -> Archive | None:
        """One archive with its transcript."""
        ...

    def delete(self, archive_id: UUID) -> None: ...


class SettingsRepo(Protocol):
    """Hub-level key-value settings (migration 0010): team_mode, terminal_app, the shift
    state document. Values are whole JSON documents, replaced atomically."""

    def get(self, key: str) -> Any | None: ...

    def set(self, key: str, value: Any) -> None: ...

    def delete(self, key: str) -> None: ...


class ChannelRepo(Protocol):
    def upsert(self, agent_id: UUID, endpoint: str, channel_token: str) -> Channel: ...

    def get(self, agent_id: UUID) -> Channel | None: ...

    def delete(self, agent_id: UUID) -> None: ...

    def heartbeat(self, agent_id: UUID) -> Channel | None:
        """Update last_heartbeat to now; None if the agent has no channel."""
        ...

    def list(self) -> list[Channel]: ...


class UnitOfWork(Protocol):
    agents: AgentRepo
    lines: LineRepo
    messages: MessageRepo
    channels: ChannelRepo
    archives: ArchiveRepo
    settings: SettingsRepo


class Storage(Protocol):
    def transaction(self) -> AbstractContextManager[UnitOfWork]: ...
