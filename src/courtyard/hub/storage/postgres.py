"""Postgres storage backend: plain SQL over a psycopg connection pool.

One Storage.transaction() = one pooled connection = one database transaction
(committed on clean exit, rolled back on exception).
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Json
from psycopg_pool import ConnectionPool

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

_MESSAGE_SELECT = """
SELECT m.*, sa.name AS sender_name, ra.name AS recipient_name,
       sa.type AS sender_type,
       sa.sme_domain AS sender_sme_domain, ra.sme_domain AS recipient_sme_domain,
       t.opened_by AS thread_opened_by
FROM messages m
LEFT JOIN agents sa ON sa.id = m.sender
LEFT JOIN agents ra ON ra.id = m.recipient
LEFT JOIN threads t ON t.id = m.thread_id
"""

_LINE_SELECT = """
SELECT l.*, aa.name AS agent_a_name, ab.name AS agent_b_name,
  (SELECT count(*) FROM messages m
    WHERE m.line_id = l.id AND m.status = 'pending_gate') AS pending_count,
  (SELECT count(*) FROM messages m
    WHERE m.line_id = l.id AND m.status = 'queued') AS queued_count,
  (SELECT count(*) FROM threads t WHERE t.line_id = l.id) AS thread_count,
  (SELECT max(m.created_at) FROM messages m WHERE m.line_id = l.id) AS last_activity_at
FROM lines l
JOIN agents aa ON aa.id = l.agent_a
JOIN agents ab ON ab.id = l.agent_b
"""


# Items 33/34: the UI reads the session-channel facts off the agent object, so agent
# reads join them in. `token`/`channel_token` are deliberately not selected here.
_AGENT_SELECT = """
SELECT a.*, c.channel_flag,
  CASE WHEN c.verify_token IS NOT NULL THEN 'pending'
       WHEN c.verify_failed_at IS NOT NULL THEN 'failed'
       WHEN c.verified_at IS NOT NULL THEN 'verified' END AS delivery_check,
  COALESCE(c.verify_failed_at, c.verified_at) AS delivery_checked_at
FROM agents a LEFT JOIN channels c ON c.agent_id = a.id
"""


class PgAgentRepo:
    def __init__(self, conn: Connection):
        self._conn = conn

    def create(
        self,
        *,
        agent_id,
        name,
        type,
        description,
        sme_domain,
        workdir,
        token_hash,
        token,
        launch,
        color,
        model,
        anti_scope=None,
    ) -> Agent:
        row = self._conn.execute(
            "INSERT INTO agents"
            " (id, name, type, description, sme_domain, anti_scope, workdir, token_hash, token,"
            "  launch, color, model)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING *",
            (
                agent_id,
                name,
                type,
                description,
                sme_domain,
                anti_scope,
                workdir,
                token_hash,
                token,
                Json(launch) if launch else None,
                color,
                model,
            ),
        ).fetchone()
        return Agent.model_validate(row)

    def get_token(self, agent_id: UUID) -> str | None:
        row = self._conn.execute("SELECT token FROM agents WHERE id = %s", (agent_id,)).fetchone()
        return row["token"] if row else None

    def set_token(self, agent_id: UUID, token_hash: str, token: str) -> None:
        self._conn.execute(
            "UPDATE agents SET token_hash = %s, token = %s WHERE id = %s",
            (token_hash, token, agent_id),
        )

    def get(self, agent_id: UUID) -> Agent | None:
        row = self._conn.execute(_AGENT_SELECT + " WHERE a.id = %s", (agent_id,)).fetchone()
        return Agent.model_validate(row) if row else None

    def get_by_name(self, name: str) -> Agent | None:
        row = self._conn.execute(_AGENT_SELECT + " WHERE a.name = %s", (name,)).fetchone()
        return Agent.model_validate(row) if row else None

    def get_by_token_hash(self, token_hash: str) -> Agent | None:
        row = self._conn.execute(
            _AGENT_SELECT + " WHERE a.token_hash = %s", (token_hash,)
        ).fetchone()
        return Agent.model_validate(row) if row else None

    def list(self) -> list[Agent]:
        rows = self._conn.execute(_AGENT_SELECT + " ORDER BY a.created_at").fetchall()
        return [Agent.model_validate(r) for r in rows]

    def update(self, agent_id: UUID, fields: dict) -> None:
        columns = ", ".join(f"{name} = %({name})s" for name in fields)
        self._conn.execute(
            # keys are validated against the editable-field allowlist by the registry
            f"UPDATE agents SET {columns} WHERE id = %(id)s",
            {**fields, "id": agent_id},
        )

    def set_status(self, agent_id: UUID, status: str) -> None:
        self._conn.execute("UPDATE agents SET status = %s WHERE id = %s", (status, agent_id))

    def touch(self, agent_id: UUID) -> None:
        self._conn.execute("UPDATE agents SET last_seen_at = now() WHERE id = %s", (agent_id,))

    def mark_removed(self, agent_id: UUID) -> None:
        self._conn.execute(
            "UPDATE agents SET removed_at = now(), status = 'gone' WHERE id = %s", (agent_id,)
        )

    def revive(
        self,
        agent_id,
        *,
        type,
        description,
        sme_domain,
        workdir,
        token_hash,
        token,
        launch,
        color,
        model,
        anti_scope=None,
    ) -> Agent | None:
        row = self._conn.execute(
            "UPDATE agents SET removed_at = NULL, status = 'invited', last_seen_at = NULL,"
            "  created_at = now(), type = %s, description = %s, sme_domain = %s,"
            "  anti_scope = %s, workdir = %s, token_hash = %s, token = %s, launch = %s,"
            "  color = %s, model = %s"
            " WHERE id = %s AND removed_at IS NOT NULL RETURNING *",
            (
                type,
                description,
                sme_domain,
                anti_scope,
                workdir,
                token_hash,
                token,
                Json(launch) if launch else None,
                color,
                model,
                agent_id,
            ),
        ).fetchone()
        if row is None:
            # a concurrent registration of the same name got there first (found by
            # review, 2026-09-10): the caller reports the name as taken, not a 500
            return None
        # the channel-derived columns (channel_flag, delivery_check) come from a join the
        # RETURNING row lacks; the channel row went at removal, so they are null anyway
        return Agent.model_validate(dict(row))


class PgLineRepo:
    def __init__(self, conn: Connection):
        self._conn = conn

    def get_or_create_locked(self, a: UUID, b: UUID, mode: str = "supervised") -> Line:
        a, b = sorted((a, b))
        self._conn.execute(
            "INSERT INTO lines (id, agent_a, agent_b, mode)"
            " VALUES (gen_random_uuid(), %s, %s, %s) ON CONFLICT (agent_a, agent_b) DO NOTHING",
            (a, b, mode),
        )
        row = self._conn.execute(
            "SELECT * FROM lines WHERE agent_a = %s AND agent_b = %s FOR UPDATE", (a, b)
        ).fetchone()
        return Line.model_validate(row)

    def get_pair_locked(self, a: UUID, b: UUID) -> Line | None:
        a, b = sorted((a, b))
        row = self._conn.execute(
            "SELECT * FROM lines WHERE agent_a = %s AND agent_b = %s FOR UPDATE", (a, b)
        ).fetchone()
        return Line.model_validate(row) if row else None

    def get(self, line_id: UUID) -> Line | None:
        row = self._conn.execute(_LINE_SELECT + " WHERE l.id = %s", (line_id,)).fetchone()
        return Line.model_validate(row) if row else None

    def get_locked(self, line_id: UUID) -> Line | None:
        # Plain row for the turn machine; enrichment is for display reads.
        row = self._conn.execute(
            "SELECT * FROM lines WHERE id = %s FOR UPDATE", (line_id,)
        ).fetchone()
        return Line.model_validate(row) if row else None

    def list(self) -> list[Line]:
        rows = self._conn.execute(_LINE_SELECT + " ORDER BY l.created_at").fetchall()
        return [Line.model_validate(r) for r in rows]

    def list_for_agent(self, agent_id: UUID) -> list[Line]:
        rows = self._conn.execute(
            _LINE_SELECT + " WHERE l.agent_a = %s OR l.agent_b = %s ORDER BY l.created_at",
            (agent_id, agent_id),
        ).fetchall()
        return [Line.model_validate(r) for r in rows]

    def set_mode(self, line_id: UUID, mode: str) -> None:
        self._conn.execute("UPDATE lines SET mode = %s WHERE id = %s", (mode, line_id))

    def set_turn(self, line_id, state, awaiting_from, in_flight_msg) -> None:
        self._conn.execute(
            "UPDATE lines SET state = %s, awaiting_from = %s, in_flight_msg = %s WHERE id = %s",
            (state, awaiting_from, in_flight_msg, line_id),
        )

    def set_open_thread(self, line_id: UUID, thread_id: UUID | None) -> None:
        self._conn.execute("UPDATE lines SET open_thread = %s WHERE id = %s", (thread_id, line_id))

    def delete(self, line_id: UUID) -> None:
        self._conn.execute("DELETE FROM lines WHERE id = %s", (line_id,))


class PgMessageRepo:
    def __init__(self, conn: Connection):
        self._conn = conn

    def insert(
        self,
        *,
        message_id,
        line_id,
        sender,
        recipient,
        kind,
        body,
        reply_to,
        status,
        thread_id=None,
    ):
        self._conn.execute(
            "INSERT INTO messages"
            " (id, line_id, seq, sender, recipient, kind, body, reply_to, status, thread_id,"
            "  delivered_at)"
            " SELECT %(id)s, %(line_id)s, COALESCE(MAX(seq), 0) + 1, %(sender)s, %(recipient)s,"
            "        %(kind)s, %(body)s, %(reply_to)s, %(status)s, %(thread_id)s,"
            "        CASE WHEN %(status)s = 'delivered' THEN now() END"
            " FROM messages WHERE line_id = %(line_id)s",
            {
                "id": message_id,
                "line_id": line_id,
                "sender": sender,
                "recipient": recipient,
                "kind": kind,
                "body": body,
                "reply_to": reply_to,
                "status": status,
                "thread_id": thread_id,
            },
        )
        return self.get(message_id)

    def get(self, message_id: UUID) -> Message | None:
        row = self._conn.execute(_MESSAGE_SELECT + " WHERE m.id = %s", (message_id,)).fetchone()
        return Message.model_validate(row) if row else None

    def list_line(self, line_id: UUID, after: int | None = None) -> list[Message]:
        rows = self._conn.execute(
            _MESSAGE_SELECT + " WHERE m.line_id = %s AND m.seq > %s ORDER BY m.seq",
            (line_id, after or 0),
        ).fetchall()
        return [Message.model_validate(r) for r in rows]

    def list_thread(self, thread_id: UUID) -> list[Message]:
        rows = self._conn.execute(
            _MESSAGE_SELECT + " WHERE m.thread_id = %s ORDER BY m.seq", (thread_id,)
        ).fetchall()
        return [Message.model_validate(r) for r in rows]

    def pending_gate(self) -> list[Message]:
        rows = self._conn.execute(
            _MESSAGE_SELECT + " WHERE m.status = 'pending_gate' ORDER BY m.created_at"
        ).fetchall()
        return [Message.model_validate(r) for r in rows]

    def take_queued_for(self, agent_id: UUID) -> list[Message]:
        rows = self._conn.execute(
            "WITH taken AS ("
            "  UPDATE messages SET status = 'delivered', delivered_at = now()"
            "  WHERE recipient = %s AND status = 'queued' RETURNING *)"
            " SELECT t.*, sa.name AS sender_name, ra.name AS recipient_name,"
            "        sa.type AS sender_type,"
            "        sa.sme_domain AS sender_sme_domain, ra.sme_domain AS recipient_sme_domain,"
            "        th.opened_by AS thread_opened_by"
            " FROM taken t"
            " LEFT JOIN agents sa ON sa.id = t.sender"
            " LEFT JOIN agents ra ON ra.id = t.recipient"
            " LEFT JOIN threads th ON th.id = t.thread_id"
            " ORDER BY t.created_at, t.seq",
            (agent_id,),
        ).fetchall()
        return [Message.model_validate(r) for r in rows]

    def list_queued_for(self, agent_id: UUID) -> list[Message]:
        rows = self._conn.execute(
            _MESSAGE_SELECT
            + " WHERE m.recipient = %s AND m.status = 'queued' ORDER BY m.created_at, m.seq",
            (agent_id,),
        ).fetchall()
        return [Message.model_validate(r) for r in rows]

    def count_queued_for(self, agent_id: UUID) -> int:
        row = self._conn.execute(
            "SELECT count(*) AS n FROM messages WHERE recipient = %s AND status = 'queued'",
            (agent_id,),
        ).fetchone()
        return row["n"]

    def count_thread(self, thread_id: UUID) -> int:
        row = self._conn.execute(
            "SELECT count(*) AS n FROM messages WHERE thread_id = %s AND kind = 'message'"
            " AND status NOT IN ('returned', 'dropped')",
            (thread_id,),
        ).fetchone()
        return row["n"]

    def list_for_recipient(self, agent_id: UUID, limit: int) -> list[Message]:
        rows = self._conn.execute(
            _MESSAGE_SELECT + " WHERE m.recipient = %s ORDER BY m.created_at DESC LIMIT %s",
            (agent_id, limit),
        ).fetchall()
        return [Message.model_validate(r) for r in rows]

    def mark_delivered(self, message_id: UUID) -> Message | None:
        row = self._conn.execute(
            "UPDATE messages SET status = 'delivered', delivered_at = now()"
            " WHERE id = %s AND status = 'queued' RETURNING id",
            (message_id,),
        ).fetchone()
        return self.get(message_id) if row else None

    def expire(self, message_id: UUID) -> Message | None:
        row = self._conn.execute(
            "UPDATE messages SET status = 'expired'"
            " WHERE id = %s AND status IN ('pending_gate', 'queued', 'delivered')"
            " RETURNING id",
            (message_id,),
        ).fetchone()
        return self.get(message_id) if row else None

    def rearm_undischarged(self, agent_id: UUID) -> list[Message]:
        rows = self._conn.execute(
            "UPDATE messages m SET status = 'queued', delivered_at = NULL"
            " FROM lines l"
            " WHERE l.id = m.line_id AND l.state = 'awaiting_reply'"
            "   AND l.awaiting_from = %s AND l.in_flight_msg = m.id"
            "   AND m.status = 'delivered'"
            " RETURNING m.id",
            (agent_id,),
        ).fetchall()
        return [self.get(r["id"]) for r in rows]

    def apply_gate(self, message_id, status, verdict, note, decided_by) -> Message:
        self._conn.execute(
            "UPDATE messages SET status = %s, gate_verdict = %s, gate_note = %s,"
            " gate_decided_by = %s, gate_decided_at = now() WHERE id = %s",
            (status, verdict, note, decided_by, message_id),
        )
        return self.get(message_id)

    def delete_line(self, line_id: UUID) -> int:
        cur = self._conn.execute("DELETE FROM messages WHERE line_id = %s", (line_id,))
        return cur.rowcount


_THREAD_SELECT = (
    "SELECT t.*, a.name AS opened_by_name FROM threads t JOIN agents a ON a.id = t.opened_by"
)


class PgThreadRepo:
    def __init__(self, conn: Connection):
        self._conn = conn

    def insert(self, *, thread_id: UUID, line_id: UUID, opened_by: UUID) -> Thread:
        self._conn.execute(
            "INSERT INTO threads (id, line_id, opened_by) VALUES (%s, %s, %s)",
            (thread_id, line_id, opened_by),
        )
        return self.get(thread_id)

    def get(self, thread_id: UUID) -> Thread | None:
        row = self._conn.execute(_THREAD_SELECT + " WHERE t.id = %s", (thread_id,)).fetchone()
        return Thread.model_validate(row) if row else None

    def list_line(self, line_id: UUID) -> list[Thread]:
        rows = self._conn.execute(
            _THREAD_SELECT + " WHERE t.line_id = %s ORDER BY t.opened_at", (line_id,)
        ).fetchall()
        return [Thread.model_validate(r) for r in rows]

    def end(self, thread_id: UUID, state: str) -> Thread | None:
        row = self._conn.execute(
            "UPDATE threads SET state = %s, ended_at = now()"
            " WHERE id = %s AND state = 'open' RETURNING id",
            (state, thread_id),
        ).fetchone()
        return self.get(thread_id) if row else None

    def expire_open(self) -> list[Thread]:
        rows = self._conn.execute(
            "UPDATE threads SET state = 'expired', ended_at = now()"
            " WHERE state = 'open' RETURNING id"
        ).fetchall()
        return [self.get(r["id"]) for r in rows]

    def delete_line(self, line_id: UUID) -> int:
        cur = self._conn.execute("DELETE FROM threads WHERE line_id = %s", (line_id,))
        return cur.rowcount


# the threads an archive holds: the transcript's messages carry their thread id (D34)
_ARCHIVE_THREADS = (
    "SELECT DISTINCT (t ->> 'thread_id')::uuid FROM jsonb_array_elements(lines_archive.transcript) t"
    " WHERE t ->> 'thread_id' IS NOT NULL"
)
# `case_files` counts what a delete takes with it (hub-memory.md section 8)
_ARCHIVE_COLUMNS = (
    "id, line_id, agent_a, agent_b, agent_a_name, agent_b_name, mode, reason,"
    " archived_at, first_at, last_at, message_count,"
    " (SELECT count(*) FROM memory WHERE memory.kind = 'case'"
    f"   AND memory.thread_id IN ({_ARCHIVE_THREADS})) AS case_files"
)
_ARCHIVE_SUMMARY = f"SELECT {_ARCHIVE_COLUMNS} FROM lines_archive"


class PgArchiveRepo:
    def __init__(self, conn: Connection):
        self._conn = conn

    def insert(
        self,
        *,
        archive_id,
        line_id,
        agent_a,
        agent_b,
        agent_a_name,
        agent_b_name,
        mode,
        reason,
        first_at,
        last_at,
        transcript,
    ) -> Archive:
        self._conn.execute(
            "INSERT INTO lines_archive (id, line_id, agent_a, agent_b, agent_a_name, agent_b_name,"
            " mode, reason, first_at, last_at, message_count, transcript)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                archive_id,
                line_id,
                agent_a,
                agent_b,
                agent_a_name,
                agent_b_name,
                mode,
                reason,
                first_at,
                last_at,
                len(transcript),
                Json(transcript),
            ),
        )
        # read back through the summary: `case_files` is computed, not a column
        row = self._conn.execute(_ARCHIVE_SUMMARY + " WHERE id = %s", (archive_id,)).fetchone()
        return Archive.model_validate(row)

    def list(self) -> list[Archive]:
        rows = self._conn.execute(_ARCHIVE_SUMMARY + " ORDER BY archived_at DESC").fetchall()
        return [Archive.model_validate(r) for r in rows]

    def get(self, archive_id: UUID) -> Archive | None:
        row = self._conn.execute(
            f"SELECT {_ARCHIVE_COLUMNS}, transcript FROM lines_archive WHERE id = %s",
            (archive_id,),
        ).fetchone()
        return Archive.model_validate(row) if row else None

    def threads_of(self, archive_id: UUID) -> list[UUID]:
        """The threads whose messages this archive holds; what its case files hang on."""
        rows = self._conn.execute(
            f"SELECT thread_id FROM lines_archive, LATERAL ({_ARCHIVE_THREADS}) AS t (thread_id)"
            " WHERE lines_archive.id = %s",
            (archive_id,),
        ).fetchall()
        return [r["thread_id"] for r in rows]

    def delete(self, archive_id: UUID) -> None:
        self._conn.execute("DELETE FROM lines_archive WHERE id = %s", (archive_id,))


_MEMORY_LISTING = (
    "SELECT id, kind, thread_id, line_id, participants, opened_by, opened_by_name, opened_at,"
    " closed_at, created_at, message_count, approved, returned, dropped, ask, resolution,"
    " verdict_text, body, scope, status, author, author_name, gate_note, decided_at,"
    " superseded_by"
)


def _memory_row(row: dict) -> MemoryRecord:
    data = dict(row)
    verdict_text = data.pop("verdict_text", "") or ""
    data["verdicts"] = [v for v in verdict_text.split("\n") if v]
    for column in ("search", "rank", "distance", "embedding"):
        data.pop(column, None)
    return MemoryRecord.model_validate(data)


# a row's vector counts as current when the model matches and, once the hub knows the
# encoder's width, the dimension too: a vector of another width under the same model name
# is re-embedded by the sweep and skipped by the search (found by review, 2026-09-10)
_CURRENT_VECTOR = (
    "(embedding IS NOT NULL AND embedding_model = %(model)s"
    " AND (%(dims)s::int IS NULL OR vector_dims(embedding) = %(dims)s::int))"
)


def _vector_literal(vector: list[float]) -> str:
    """pgvector's text input form: `[0.1,0.2,...]`."""
    return "[" + ",".join(repr(float(v)) for v in vector) + "]"


class PgMemoryRepo:
    def __init__(self, conn: Connection):
        self._conn = conn

    def insert(
        self,
        *,
        record_id,
        kind,
        thread_id,
        line_id,
        participants,
        opened_by,
        opened_by_name,
        opened_at,
        closed_at,
        message_count,
        approved,
        returned,
        dropped,
        ask,
        resolution,
        verdicts,
        document,
    ) -> MemoryRecord:
        names_text = " ".join(p["name"] for p in participants)
        domains_text = " ".join(p.get("sme_domain") or "" for p in participants)
        row = self._conn.execute(
            "INSERT INTO memory (id, kind, thread_id, line_id, participants, participant_ids,"
            " opened_by, opened_by_name, opened_at, closed_at, message_count, approved, returned,"
            " dropped, ask, resolution, verdict_text, names_text, domains_text, document)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
            " RETURNING *",
            (
                record_id,
                kind,
                thread_id,
                line_id,
                Json(participants),
                [UUID(str(p["id"])) for p in participants],
                opened_by,
                opened_by_name,
                opened_at,
                closed_at,
                message_count,
                approved,
                returned,
                dropped,
                ask,
                resolution,
                "\n".join(verdicts),
                names_text,
                domains_text,
                Json(document),
            ),
        ).fetchone()
        return _memory_row(row)

    def insert_note(
        self, *, record_id, body, scope, status, author, author_name, line_id, participants
    ) -> MemoryRecord:
        row = self._conn.execute(
            "INSERT INTO memory (id, kind, line_id, participants, participant_ids, ask,"
            " resolution, names_text, domains_text, document, body, scope, status, author,"
            " author_name)"
            " VALUES (%s, 'note', %s, %s, %s, '', '', %s, %s, %s, %s, %s, %s, %s, %s)"
            " RETURNING *",
            (
                record_id,
                line_id,
                Json(participants),
                [UUID(str(p["id"])) for p in participants],
                " ".join(p["name"] for p in participants),
                " ".join(p.get("sme_domain") or "" for p in participants),
                Json({}),
                body,
                scope,
                status,
                author,
                author_name,
            ),
        ).fetchone()
        return _memory_row(row)

    def decide_note(
        self, record_id: UUID, status: str, gate_note: str | None
    ) -> MemoryRecord | None:
        row = self._conn.execute(
            "UPDATE memory SET status = %s, gate_note = %s, decided_at = now()"
            " WHERE id = %s AND kind = 'note' AND status = 'pending' RETURNING *",
            (status, gate_note, record_id),
        ).fetchone()
        return _memory_row(row) if row else None

    def list_pending(self) -> list[MemoryRecord]:
        rows = self._conn.execute(
            _MEMORY_LISTING + " FROM memory WHERE status = 'pending' ORDER BY created_at"
        ).fetchall()
        return [_memory_row(r) for r in rows]

    def get(self, record_id: UUID) -> MemoryRecord | None:
        row = self._conn.execute("SELECT * FROM memory WHERE id = %s", (record_id,)).fetchone()
        return _memory_row(row) if row else None

    def export(
        self,
        *,
        participant: UUID | None = None,
        line_id: UUID | None = None,
        since: datetime | None = None,
    ) -> list[MemoryRecord]:
        """Every record in full, oldest first: superseded ones and notes in every gate
        state included, with their status (hub-memory.md section 6). The filters are the
        search's, so an external system pulls incrementally by date."""
        where, params = ["true"], {}
        if participant is not None:
            where.append("%(who)s = ANY(participant_ids)")
            params["who"] = participant
        if line_id is not None:
            where.append("line_id = %(line)s")
            params["line"] = line_id
        if since is not None:
            where.append("created_at >= %(since)s")
            params["since"] = since
        rows = self._conn.execute(
            "SELECT * FROM memory WHERE " + " AND ".join(where) + " ORDER BY created_at, id",
            params,
        ).fetchall()
        return [_memory_row(r) for r in rows]

    def delete_cases(self, thread_ids: list[UUID]) -> int:
        """Retention (hub-memory.md section 8): the case files of these threads go with
        the archive they were distilled from. Notes are never touched."""
        if not thread_ids:
            return 0
        rows = self._conn.execute(
            "DELETE FROM memory WHERE kind = 'case' AND thread_id = ANY(%s) RETURNING id",
            (thread_ids,),
        ).fetchall()
        return len(rows)

    @staticmethod
    def _visible(where: list[str], viewer, all_cases) -> None:
        # what the reader may see (hub-memory.md section 8): cases for everyone under
        # auto, for their participants under manual; accepted notes by scope
        if viewer is None:
            where.append("(kind = 'case' OR status = 'accepted')")
        else:
            case_rule = "TRUE" if all_cases else "participant_ids @> %(viewer)s::uuid[]"
            where.append(
                f"((kind = 'case' AND {case_rule}) OR (kind = 'note' AND status = 'accepted'"
                " AND (scope = 'team' OR participant_ids @> %(viewer)s::uuid[])))"
            )

    def search(
        self,
        *,
        question,
        participant,
        line_id,
        since,
        limit,
        viewer=None,
        all_cases=True,
        mode="exact",
        query_vector=None,
        model=None,
    ) -> list[MemoryRecord]:
        where = ["superseded_by IS NULL"]
        self._visible(where, viewer, all_cases)
        named: dict = {"viewer": [viewer] if viewer else None}
        if participant is not None:
            where.append("participant_ids @> %(participant)s::uuid[]")
            named["participant"] = [participant]
        if line_id is not None:
            where.append("line_id = %(line_id)s")
            named["line_id"] = line_id
        if since is not None:
            where.append("created_at >= %(since)s")
            named["since"] = since
        question = (question or "").strip()
        can_vector = bool(question) and query_vector is not None and model is not None
        if mode == "vector" and not can_vector:
            mode = "exact"
        if mode == "hybrid" and not can_vector:
            mode = "exact"
        if mode == "exact":
            return self._search_exact(where, named, question, limit)
        if mode == "vector":
            return self._search_vector(where, named, query_vector, model, limit)
        # hybrid: reciprocal rank fusion of the two rankings, each fetched a little deeper
        deep = limit * 3
        exact = self._search_exact(where, named, question, deep)
        near = self._search_vector(where, named, query_vector, model, deep)
        score: dict = {}
        by_id: dict = {}
        for ranking in (exact, near):
            for rank, record in enumerate(ranking, 1):
                score[record.id] = score.get(record.id, 0.0) + 1.0 / (60 + rank)
                by_id[record.id] = record
        ordered = sorted(by_id.values(), key=lambda r: -score[r.id])
        return ordered[:limit]

    def _search_exact(self, where, named, question, limit) -> list[MemoryRecord]:
        select = _MEMORY_LISTING + " FROM memory"
        order = " ORDER BY created_at DESC"
        where = list(where)
        params = dict(named)
        if question:
            # websearch syntax: plain words, quoted phrases, `or`, `-not`; the weights of
            # migrations 0020/0021 put the ask, a note's body and the domains first
            select = (
                _MEMORY_LISTING + ", ts_rank_cd(search, q) AS rank"
                " FROM memory, websearch_to_tsquery('english', %(question)s) q"
            )
            params["question"] = question
            where.append("search @@ q")
            order = " ORDER BY rank DESC, created_at DESC"
        params["limit"] = limit
        rows = self._conn.execute(
            select + " WHERE " + " AND ".join(where) + order + " LIMIT %(limit)s", params
        ).fetchall()
        return [_memory_row(r) for r in rows]

    def _search_vector(self, where, named, query_vector, model, limit) -> list[MemoryRecord]:
        # the dimension filter keeps `<=>` from failing on a row embedded by an earlier
        # encoder that kept the model name but not its width (found by review, 2026-09-10):
        # such rows are simply not there for this search until the sweep re-embeds them
        where = [
            *where,
            "embedding IS NOT NULL",
            "embedding_model = %(model)s",
            "vector_dims(embedding) = %(dims)s",
        ]
        params = {
            **named,
            "model": model,
            "dims": len(query_vector),
            "qvec": _vector_literal(query_vector),
            "limit": limit,
        }
        rows = self._conn.execute(
            _MEMORY_LISTING
            + ", (embedding <=> %(qvec)s::vector) AS distance FROM memory WHERE "
            + " AND ".join(where)
            + " ORDER BY distance ASC, created_at DESC LIMIT %(limit)s",
            params,
        ).fetchall()
        return [_memory_row(r) for r in rows]

    def count(self) -> int:
        return self._conn.execute("SELECT count(*) AS n FROM memory").fetchone()["n"]

    def searchable(self, question: str) -> bool:
        row = self._conn.execute(
            "SELECT numnode(websearch_to_tsquery('english', %s)) AS n", (question,)
        ).fetchone()
        return row["n"] > 0

    def set_embedding(self, record_id: UUID, model: str, vector: list[float]) -> None:
        self._conn.execute(
            "UPDATE memory SET embedding = %s::vector, embedding_model = %s, embedded_at = now()"
            " WHERE id = %s",
            (_vector_literal(vector), model, record_id),
        )

    def list_unembedded(
        self, model: str, limit: int, dims: int | None = None
    ) -> list[MemoryRecord]:
        rows = self._conn.execute(
            _MEMORY_LISTING + " FROM memory"
            " WHERE (kind = 'case' OR status = 'accepted') AND superseded_by IS NULL"
            "   AND NOT " + _CURRENT_VECTOR + " ORDER BY created_at LIMIT %(limit)s",
            {"model": model, "dims": dims, "limit": limit},
        ).fetchall()
        return [_memory_row(r) for r in rows]

    def embedding_stats(self, model: str, dims: int | None = None) -> dict[str, int]:
        row = self._conn.execute(
            "SELECT count(*) AS total, count(*) FILTER (WHERE " + _CURRENT_VECTOR + ") AS embedded"
            " FROM memory WHERE (kind = 'case' OR status = 'accepted') AND superseded_by IS NULL",
            {"model": model, "dims": dims},
        ).fetchone()
        return {"total": row["total"], "embedded": row["embedded"]}


class PgChannelRepo:
    def __init__(self, conn: Connection):
        self._conn = conn

    def upsert(
        self, agent_id: UUID, endpoint: str, channel_token: str, channel_flag: str = "unknown"
    ) -> Channel:
        # A new attach is a new session: the previous session's flag report and
        # delivery-check verdict do not carry over (items 33/34).
        row = self._conn.execute(
            "INSERT INTO channels (agent_id, endpoint, channel_token, channel_flag)"
            " VALUES (%s, %s, %s, %s)"
            " ON CONFLICT (agent_id) DO UPDATE SET endpoint = EXCLUDED.endpoint,"
            "   channel_token = EXCLUDED.channel_token,"
            "   channel_flag = EXCLUDED.channel_flag,"
            "   registered_at = now(), last_heartbeat = now(),"
            "   verify_token = NULL, verify_sent_at = NULL,"
            "   verified_at = NULL, verify_failed_at = NULL"
            " RETURNING *",
            (agent_id, endpoint, channel_token, channel_flag),
        ).fetchone()
        return Channel.model_validate(row)

    # -- delivery verification (item 34, D30) ------------------------------------------

    def begin_verify(self, agent_id: UUID, token: str) -> Channel | None:
        """Open a check: the nonce goes out; a previous failure verdict is cleared."""
        row = self._conn.execute(
            "UPDATE channels SET verify_token = %s, verify_sent_at = now(),"
            " verify_failed_at = NULL WHERE agent_id = %s RETURNING *",
            (token, agent_id),
        ).fetchone()
        return Channel.model_validate(row) if row else None

    def ack_verify(self, agent_id: UUID, token: str) -> Channel | None:
        """Close the check as verified; None when the token matches no open check."""
        row = self._conn.execute(
            "UPDATE channels SET verified_at = now(), verify_token = NULL,"
            " verify_sent_at = NULL, verify_failed_at = NULL"
            " WHERE agent_id = %s AND verify_token = %s RETURNING *",
            (agent_id, token),
        ).fetchone()
        return Channel.model_validate(row) if row else None

    def fail_verify(self, agent_id: UUID) -> Channel | None:
        """Close the agent's open check as failed (push refused outright)."""
        row = self._conn.execute(
            "UPDATE channels SET verify_failed_at = now(), verify_token = NULL,"
            " verify_sent_at = NULL WHERE agent_id = %s AND verify_token IS NOT NULL"
            " RETURNING *",
            (agent_id,),
        ).fetchone()
        return Channel.model_validate(row) if row else None

    def expire_verifies(self, timeout_seconds: float) -> list[UUID]:
        """Close every check older than the timeout as failed; the agents whose changed."""
        rows = self._conn.execute(
            "UPDATE channels SET verify_failed_at = now(), verify_token = NULL,"
            " verify_sent_at = NULL WHERE verify_token IS NOT NULL"
            " AND verify_sent_at < now() - make_interval(secs => %s)"
            " RETURNING agent_id",
            (timeout_seconds,),
        ).fetchall()
        return [r["agent_id"] for r in rows]

    def get(self, agent_id: UUID) -> Channel | None:
        row = self._conn.execute(
            "SELECT * FROM channels WHERE agent_id = %s", (agent_id,)
        ).fetchone()
        return Channel.model_validate(row) if row else None

    def delete(self, agent_id: UUID) -> None:
        self._conn.execute("DELETE FROM channels WHERE agent_id = %s", (agent_id,))

    def heartbeat(self, agent_id: UUID) -> Channel | None:
        row = self._conn.execute(
            "UPDATE channels SET last_heartbeat = now() WHERE agent_id = %s RETURNING *",
            (agent_id,),
        ).fetchone()
        return Channel.model_validate(row) if row else None

    def list(self) -> list[Channel]:
        rows = self._conn.execute(
            "SELECT *, EXTRACT(EPOCH FROM (now() - last_heartbeat)) AS heartbeat_age_seconds"
            " FROM channels ORDER BY registered_at"
        ).fetchall()
        return [Channel.model_validate(r) for r in rows]


# The `loaded` column carries the cached charter document; the model calls it `charter`.
_TEAM_SELECT = (
    "SELECT id, charter_dir, name, is_current, loaded AS charter, load_report,"
    " loaded_at, created_at FROM teams"
)


class PgTeamRepo:
    def __init__(self, conn: Connection):
        self._conn = conn

    def insert(self, *, team_id, charter_dir, name, loaded, load_report) -> Team:
        self._conn.execute(
            "INSERT INTO teams (id, charter_dir, name, loaded, load_report, loaded_at)"
            " VALUES (%s, %s, %s, %s, %s, now())",
            (team_id, charter_dir, name, Json(loaded) if loaded else None, Json(load_report)),
        )
        return self.get(team_id)

    def get(self, team_id: UUID) -> Team | None:
        row = self._conn.execute(_TEAM_SELECT + " WHERE id = %s", (team_id,)).fetchone()
        return Team.model_validate(row) if row else None

    def get_by_dir(self, charter_dir: str) -> Team | None:
        row = self._conn.execute(
            _TEAM_SELECT + " WHERE charter_dir = %s", (charter_dir,)
        ).fetchone()
        return Team.model_validate(row) if row else None

    def list(self) -> list[Team]:
        rows = self._conn.execute(_TEAM_SELECT + " ORDER BY created_at").fetchall()
        return [Team.model_validate(r) for r in rows]

    def set_loaded(self, team_id, name, loaded, load_report) -> Team | None:
        row = self._conn.execute(
            "UPDATE teams SET name = %s, loaded = %s, load_report = %s, loaded_at = now()"
            " WHERE id = %s RETURNING id",
            (name, Json(loaded) if loaded else None, Json(load_report), team_id),
        ).fetchone()
        return self.get(team_id) if row else None

    def set_current(self, team_id: UUID | None) -> None:
        self._conn.execute("UPDATE teams SET is_current = false WHERE is_current")
        if team_id is not None:
            self._conn.execute("UPDATE teams SET is_current = true WHERE id = %s", (team_id,))

    def delete(self, team_id: UUID) -> None:
        self._conn.execute("DELETE FROM teams WHERE id = %s", (team_id,))


class PgSettingsRepo:
    def __init__(self, conn: Connection):
        self._conn = conn

    def get(self, key: str) -> Any | None:
        row = self._conn.execute("SELECT value FROM settings WHERE key = %s", (key,)).fetchone()
        return row["value"] if row else None

    def set(self, key: str, value: Any) -> None:
        self._conn.execute(
            "INSERT INTO settings (key, value) VALUES (%s, %s)"
            " ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()",
            (key, Json(value)),
        )

    def delete(self, key: str) -> None:
        self._conn.execute("DELETE FROM settings WHERE key = %s", (key,))


class PgUnitOfWork:
    def __init__(self, conn: Connection):
        self.agents = PgAgentRepo(conn)
        self.lines = PgLineRepo(conn)
        self.messages = PgMessageRepo(conn)
        self.threads = PgThreadRepo(conn)
        self.channels = PgChannelRepo(conn)
        self.archives = PgArchiveRepo(conn)
        self.settings = PgSettingsRepo(conn)
        self.teams = PgTeamRepo(conn)
        self.memory = PgMemoryRepo(conn)


class PostgresStorage:
    def __init__(self, conninfo: str, max_size: int = 10):
        self._pool = ConnectionPool(
            conninfo,
            min_size=1,
            max_size=max_size,
            open=False,
            kwargs={"row_factory": dict_row},
        )

    def open(self) -> None:
        self._pool.open(wait=True, timeout=30)

    def close(self) -> None:
        self._pool.close()

    @contextmanager
    def transaction(self) -> Any:
        with self._pool.connection() as conn:
            yield PgUnitOfWork(conn)
