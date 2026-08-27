"""Postgres storage backend: plain SQL over a psycopg connection pool.

One Storage.transaction() = one pooled connection = one database transaction
(committed on clean exit, rolled back on exception).
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Json
from psycopg_pool import ConnectionPool

from courtyard.common.models import Agent, Archive, Channel, Line, Message

_MESSAGE_SELECT = """
SELECT m.*, sa.name AS sender_name, ra.name AS recipient_name,
       sa.type AS sender_type,
       sa.sme_domain AS sender_sme_domain, ra.sme_domain AS recipient_sme_domain
FROM messages m
LEFT JOIN agents sa ON sa.id = m.sender
LEFT JOIN agents ra ON ra.id = m.recipient
"""

_LINE_SELECT = """
SELECT l.*, aa.name AS agent_a_name, ab.name AS agent_b_name,
  (SELECT count(*) FROM messages m
    WHERE m.line_id = l.id AND m.status = 'pending_gate') AS pending_count,
  (SELECT count(*) FROM messages m
    WHERE m.line_id = l.id AND m.status = 'queued') AS queued_count,
  (SELECT max(m.created_at) FROM messages m WHERE m.line_id = l.id) AS last_activity_at
FROM lines l
JOIN agents aa ON aa.id = l.agent_a
JOIN agents ab ON ab.id = l.agent_b
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
    ) -> Agent:
        row = self._conn.execute(
            "INSERT INTO agents"
            " (id, name, type, description, sme_domain, workdir, token_hash, token, launch,"
            "  color, model)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING *",
            (
                agent_id,
                name,
                type,
                description,
                sme_domain,
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
        row = self._conn.execute("SELECT * FROM agents WHERE id = %s", (agent_id,)).fetchone()
        return Agent.model_validate(row) if row else None

    def get_by_name(self, name: str) -> Agent | None:
        row = self._conn.execute("SELECT * FROM agents WHERE name = %s", (name,)).fetchone()
        return Agent.model_validate(row) if row else None

    def get_by_token_hash(self, token_hash: str) -> Agent | None:
        row = self._conn.execute(
            "SELECT * FROM agents WHERE token_hash = %s", (token_hash,)
        ).fetchone()
        return Agent.model_validate(row) if row else None

    def list(self) -> list[Agent]:
        rows = self._conn.execute("SELECT * FROM agents ORDER BY created_at").fetchall()
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

    def delete(self, line_id: UUID) -> None:
        self._conn.execute("DELETE FROM lines WHERE id = %s", (line_id,))


class PgMessageRepo:
    def __init__(self, conn: Connection):
        self._conn = conn

    def insert(self, *, message_id, line_id, sender, recipient, kind, body, reply_to, status):
        self._conn.execute(
            "INSERT INTO messages"
            " (id, line_id, seq, sender, recipient, kind, body, reply_to, status, delivered_at)"
            " SELECT %(id)s, %(line_id)s, COALESCE(MAX(seq), 0) + 1, %(sender)s, %(recipient)s,"
            "        %(kind)s, %(body)s, %(reply_to)s, %(status)s,"
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
            "        sa.sme_domain AS sender_sme_domain, ra.sme_domain AS recipient_sme_domain"
            " FROM taken t"
            " LEFT JOIN agents sa ON sa.id = t.sender"
            " LEFT JOIN agents ra ON ra.id = t.recipient"
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


_ARCHIVE_SUMMARY = (
    "SELECT id, line_id, agent_a, agent_b, agent_a_name, agent_b_name, mode, reason,"
    " archived_at, first_at, last_at, message_count FROM lines_archive"
)


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
        row = self._conn.execute(
            "INSERT INTO lines_archive (id, line_id, agent_a, agent_b, agent_a_name, agent_b_name,"
            " mode, reason, first_at, last_at, message_count, transcript)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
            " RETURNING id, line_id, agent_a, agent_b, agent_a_name, agent_b_name, mode, reason,"
            " archived_at, first_at, last_at, message_count",
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
        ).fetchone()
        return Archive.model_validate(row)

    def list(self) -> list[Archive]:
        rows = self._conn.execute(_ARCHIVE_SUMMARY + " ORDER BY archived_at DESC").fetchall()
        return [Archive.model_validate(r) for r in rows]

    def get(self, archive_id: UUID) -> Archive | None:
        row = self._conn.execute(
            "SELECT * FROM lines_archive WHERE id = %s", (archive_id,)
        ).fetchone()
        return Archive.model_validate(row) if row else None

    def delete(self, archive_id: UUID) -> None:
        self._conn.execute("DELETE FROM lines_archive WHERE id = %s", (archive_id,))


class PgChannelRepo:
    def __init__(self, conn: Connection):
        self._conn = conn

    def upsert(self, agent_id: UUID, endpoint: str, channel_token: str) -> Channel:
        row = self._conn.execute(
            "INSERT INTO channels (agent_id, endpoint, channel_token)"
            " VALUES (%s, %s, %s)"
            " ON CONFLICT (agent_id) DO UPDATE SET endpoint = EXCLUDED.endpoint,"
            "   channel_token = EXCLUDED.channel_token,"
            "   registered_at = now(), last_heartbeat = now()"
            " RETURNING *",
            (agent_id, endpoint, channel_token),
        ).fetchone()
        return Channel.model_validate(row)

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
        self.channels = PgChannelRepo(conn)
        self.archives = PgArchiveRepo(conn)
        self.settings = PgSettingsRepo(conn)


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
