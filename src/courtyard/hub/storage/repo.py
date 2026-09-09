"""Repository interfaces (design doc §9.1). The hub is the single writer; every mutating
service operation runs inside exactly one Storage.transaction()."""

from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from courtyard.common.models import (
    Agent,
    Archive,
    Channel,
    Line,
    MemoryRecord,
    Message,
    Team,
    Thread,
)


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
        anti_scope: str | None = None,
    ) -> Agent: ...

    def get(self, agent_id: UUID) -> Agent | None: ...

    def update(self, agent_id: UUID, fields: dict) -> None:
        """Set the operator-editable columns (WP-D): description, sme_domain, anti_scope,
        workdir, model, color. None values clear. Caller validates which keys are allowed."""
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

    def revive(
        self,
        agent_id: UUID,
        *,
        type: str,
        description: str | None,
        sme_domain: str | None,
        workdir: str | None,
        token_hash: str,
        token: str,
        launch: dict[str, Any] | None,
        color: str | None,
        model: str | None,
        anti_scope: str | None = None,
    ) -> Agent:
        """Register a removed name again on its own row: removal undone, every
        descriptive field and the type replaced, a new token, liveness reset to
        `invited`, created_at = now. The row (and so the id) is the one the archives
        and old messages point at; nothing else of the old life survives."""
        ...


class LineRepo(Protocol):
    def get_or_create_locked(self, a: UUID, b: UUID, mode: str = "supervised") -> Line:
        """Return the line for the (unordered) pair, row-locked; create it if missing.
        `mode` applies only on creation (7c: the operator's Admin default); an existing
        line keeps its own dial."""
        ...

    def get_pair_locked(self, a: UUID, b: UUID) -> Line | None:
        """The line for the (unordered) pair, row-locked — or None. The existence check
        behind manual discovery (§5.8): the line IS the permission, so no creation here."""
        ...

    def get(self, line_id: UUID) -> Line | None: ...

    def get_locked(self, line_id: UUID) -> Line | None: ...

    def list(self) -> list[Line]: ...

    def list_for_agent(self, agent_id: UUID) -> list[Line]: ...

    def set_mode(self, line_id: UUID, mode: str) -> None: ...

    def set_turn(
        self, line_id: UUID, state: str, awaiting_from: UUID | None, in_flight_msg: UUID | None
    ) -> None: ...

    def set_open_thread(self, line_id: UUID, thread_id: UUID | None) -> None: ...

    def delete(self, line_id: UUID) -> None:
        """Remove the line row (its messages and threads must already be gone)."""
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
        thread_id: UUID | None = None,
    ) -> Message:
        """Insert with the next per-line seq. Caller must hold the line row lock."""
        ...

    def get(self, message_id: UUID) -> Message | None: ...

    def list_line(self, line_id: UUID, after: int | None = None) -> list[Message]: ...

    def list_thread(self, thread_id: UUID) -> list[Message]:
        """Every message of one thread, in seq order (the case file's material)."""
        ...

    def pending_gate(self) -> list[Message]: ...

    def take_queued_for(self, agent_id: UUID) -> list[Message]:
        """Return this agent's queued messages and mark them delivered (the pull path)."""
        ...

    def list_queued_for(self, agent_id: UUID) -> list[Message]:
        """The agent's queued backlog, oldest first, without consuming it (the push path)."""
        ...

    def count_queued_for(self, agent_id: UUID) -> int: ...

    def count_thread(self, thread_id: UUID) -> int:
        """The thread's budget-relevant size (D34 §5 item 2): its `message`-kind rows,
        not counting returned or dropped ones — those never reached anyone."""
        ...

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


class ThreadRepo(Protocol):
    """Threads (design threads.md, D34). Callers hold the line row lock for every
    mutation — thread state and the line's `open_thread` pointer move together."""

    def insert(self, *, thread_id: UUID, line_id: UUID, opened_by: UUID) -> Thread: ...

    def get(self, thread_id: UUID) -> Thread | None: ...

    def list_line(self, line_id: UUID) -> list[Thread]: ...

    def end(self, thread_id: UUID, state: str) -> Thread | None:
        """open -> closed | expired | locked, with ended_at = now(). None when the
        thread was not open (already ended: nothing to do, nothing overwritten)."""
        ...

    def expire_open(self) -> list[Thread]:
        """End of shift (D34 extends D24): every open thread becomes `expired`."""
        ...

    def delete_line(self, line_id: UUID) -> int:
        """Delete a line's threads (its messages must already be gone — archive first)."""
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


class TeamRepo(Protocol):
    """The team charter registry (design team-charter.md, D33): registered charter
    directories with what the hub last loaded from each. At most one row is current."""

    def insert(
        self,
        *,
        team_id: UUID,
        charter_dir: str,
        name: str | None,
        loaded: dict | None,
        load_report: list[str],
    ) -> Team: ...

    def get(self, team_id: UUID) -> Team | None: ...

    def get_by_dir(self, charter_dir: str) -> Team | None: ...

    def list(self) -> list[Team]: ...

    def set_loaded(
        self, team_id: UUID, name: str | None, loaded: dict | None, load_report: list[str]
    ) -> Team | None:
        """Record a reload: the cached charter, its report, and loaded_at = now."""
        ...

    def set_current(self, team_id: UUID | None) -> None:
        """Make exactly this team current (None = no current team)."""
        ...

    def delete(self, team_id: UUID) -> None: ...


class ChannelRepo(Protocol):
    def upsert(
        self, agent_id: UUID, endpoint: str, channel_token: str, channel_flag: str = "unknown"
    ) -> Channel: ...

    def get(self, agent_id: UUID) -> Channel | None: ...

    def delete(self, agent_id: UUID) -> None: ...

    def heartbeat(self, agent_id: UUID) -> Channel | None:
        """Update last_heartbeat to now; None if the agent has no channel."""
        ...

    def list(self) -> list[Channel]: ...

    # delivery verification (item 34, D30)
    def begin_verify(self, agent_id: UUID, token: str) -> Channel | None: ...

    def ack_verify(self, agent_id: UUID, token: str) -> Channel | None: ...

    def fail_verify(self, agent_id: UUID) -> Channel | None: ...

    def expire_verifies(self, timeout_seconds: float) -> list[UUID]: ...


class MemoryRepo(Protocol):
    """Hub memory (design hub-memory.md, migration 0020): case files and notes. Written at
    thread close; read by recall (agents, bounded and filtered) and by the Memory page."""

    def insert(
        self,
        *,
        record_id: UUID,
        kind: str,
        thread_id: UUID | None,
        line_id: UUID | None,
        participants: list[dict],
        opened_by: UUID | None,
        opened_by_name: str | None,
        opened_at: datetime | None,
        closed_at: datetime | None,
        message_count: int,
        approved: int,
        returned: int,
        dropped: int,
        ask: str,
        resolution: str,
        verdicts: list[str],
        document: dict,
    ) -> MemoryRecord: ...

    def get(self, record_id: UUID) -> MemoryRecord | None:
        """One record with its document."""
        ...

    def insert_note(
        self,
        *,
        record_id: UUID,
        body: str,
        scope: str,
        status: str,
        author: UUID,
        author_name: str,
        line_id: UUID | None,
        participants: list[dict],
    ) -> MemoryRecord: ...

    def decide_note(
        self, record_id: UUID, status: str, gate_note: str | None
    ) -> MemoryRecord | None:
        """Rule on a pending note: accepted, returned or dropped; None if it was not pending."""
        ...

    def list_pending(self) -> list[MemoryRecord]:
        """Notes waiting for the operator, oldest first."""
        ...

    def search(
        self,
        *,
        question: str | None,
        participant: UUID | None,
        line_id: UUID | None,
        since: datetime | None,
        limit: int,
        viewer: UUID | None = None,
        all_cases: bool = True,
    ) -> list[MemoryRecord]:
        """Trimmed listing (no document): best full-text match first when there is a
        question (domain-aware weights, migrations 0020/0021), newest first otherwise.
        Every filter narrows before ranking. Superseded records and notes that are not
        `accepted` are left out. `viewer` is the reading agent, when there is one: a
        line-scoped note is seen only by that line's agents, and with `all_cases` False
        (manual discovery) the viewer sees only the case files it appears in."""
        ...

    def count(self) -> int: ...


class UnitOfWork(Protocol):
    agents: AgentRepo
    lines: LineRepo
    messages: MessageRepo
    threads: ThreadRepo
    channels: ChannelRepo
    archives: ArchiveRepo
    settings: SettingsRepo
    teams: TeamRepo
    memory: MemoryRepo


class Storage(Protocol):
    def transaction(self) -> AbstractContextManager[UnitOfWork]: ...
