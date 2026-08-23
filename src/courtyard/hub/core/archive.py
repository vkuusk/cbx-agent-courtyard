"""Archiving a line's history (design §5.7, D20).

A line's history is the queue while the line lives; archived, it becomes one immutable
document in `lines_archive`. Two doors, one function: the operator archives a line from
the board (the line continues, empty and idle), and removing an agent archives every line
it was on and drops those lines — they could never be used again.
"""

from __future__ import annotations

import logging
from uuid import UUID, uuid4

from courtyard.common.models import Archive, Line, Message
from courtyard.hub.core.errors import ArchiveNotFound, LineNotFound
from courtyard.hub.core.events import EventBus
from courtyard.hub.storage.repo import Storage, UnitOfWork

logger = logging.getLogger("courtyard.hub")


def archive_line_in(
    uow: UnitOfWork, line: Line, reason: str, *, keep_line: bool
) -> tuple[Archive, Message | None]:
    """Inside the caller's transaction, with the line row locked: copy the history into
    one archive document, delete it, reset the line to idle. With `keep_line` the line
    stays and gets a system entry saying what happened; without it the line row goes too.
    Returns the archive (summary) and the system entry, if any."""
    messages = uow.messages.list_line(line.id)
    agent_a = uow.agents.get(line.agent_a)
    agent_b = uow.agents.get(line.agent_b)
    archive = uow.archives.insert(
        archive_id=uuid4(),
        line_id=line.id,
        agent_a=line.agent_a,
        agent_b=line.agent_b,
        agent_a_name=agent_a.name,
        agent_b_name=agent_b.name,
        mode=line.mode,
        reason=reason,
        first_at=messages[0].created_at if messages else None,
        last_at=messages[-1].created_at if messages else None,
        transcript=[m.model_dump(mode="json") for m in messages],
    )
    uow.lines.set_turn(line.id, "idle", None, None)  # drop the in-flight reference first
    uow.messages.delete_line(line.id)
    entry = None
    if keep_line:
        n = len(messages)
        entry = uow.messages.insert(
            message_id=uuid4(),
            line_id=line.id,
            sender=None,
            recipient=None,  # log-only board entry
            kind="system",
            body=f"history archived by the operator ({n} message{'s' if n != 1 else ''})",
            reply_to=None,
            status="delivered",
        )
    else:
        uow.lines.delete(line.id)
    return archive, entry


class Archiver:
    def __init__(self, storage: Storage, events: EventBus):
        self._storage = storage
        self._events = events

    def archive_line(self, line_id: UUID) -> Archive:
        """Operator action: archive the history so far; the line continues empty and idle."""
        with self._storage.transaction() as uow:
            line = uow.lines.get_locked(line_id)
            if line is None:
                raise LineNotFound("no such line")
            archive, entry = archive_line_in(uow, line, "operator", keep_line=True)
            line = uow.lines.get(line_id)
        self._events.publish("archive", archive)
        self._events.publish("message", entry)
        self._events.publish("line", line)
        return archive

    def reconcile(self) -> list[Archive]:
        """Startup: lines whose participant was removed before archiving existed."""
        archives: list[Archive] = []
        with self._storage.transaction() as uow:
            for line in uow.lines.list():
                agents = (uow.agents.get(line.agent_a), uow.agents.get(line.agent_b))
                if any(a.removed_at is not None for a in agents):
                    locked = uow.lines.get_locked(line.id)
                    archives.append(
                        archive_line_in(uow, locked, "agent_removed", keep_line=False)[0]
                    )
        for archive in archives:
            self._events.publish("archive", archive)
        if archives:
            logger.info("archived %d line(s) of removed agents", len(archives))
        return archives

    def list(self) -> list[Archive]:
        with self._storage.transaction() as uow:
            return uow.archives.list()

    def get(self, archive_id: UUID) -> Archive:
        with self._storage.transaction() as uow:
            archive = uow.archives.get(archive_id)
        if archive is None:
            raise ArchiveNotFound("no such archive")
        return archive

    def delete(self, archive_id: UUID) -> None:
        with self._storage.transaction() as uow:
            if uow.archives.get(archive_id) is None:
                raise ArchiveNotFound("no such archive")
            uow.archives.delete(archive_id)
