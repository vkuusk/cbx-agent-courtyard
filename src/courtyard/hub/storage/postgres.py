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

from courtyard.common.models import Agent, Channel, Line, Message

_MESSAGE_SELECT = """
SELECT m.*, sa.name AS sender_name, ra.name AS recipient_name
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

    def create(self, *, agent_id, name, type, description, workdir, token_hash, launch) -> Agent:
        row = self._conn.execute(
            "INSERT INTO agents (id, name, type, description, workdir, token_hash, launch)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING *",
            (
                agent_id,
                name,
                type,
                description,
                workdir,
                token_hash,
                Json(launch) if launch else None,
            ),
        ).fetchone()
        return Agent.model_validate(row)

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

    def get_or_create_locked(self, a: UUID, b: UUID) -> Line:
        a, b = sorted((a, b))
        self._conn.execute(
            "INSERT INTO lines (id, agent_a, agent_b)"
            " VALUES (gen_random_uuid(), %s, %s) ON CONFLICT (agent_a, agent_b) DO NOTHING",
            (a, b),
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
            " SELECT t.*, sa.name AS sender_name, ra.name AS recipient_name"
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

    def mark_delivered(self, message_id: UUID) -> Message | None:
        row = self._conn.execute(
            "UPDATE messages SET status = 'delivered', delivered_at = now()"
            " WHERE id = %s AND status = 'queued' RETURNING id",
            (message_id,),
        ).fetchone()
        return self.get(message_id) if row else None

    def apply_gate(self, message_id, status, verdict, note, decided_by) -> Message:
        self._conn.execute(
            "UPDATE messages SET status = %s, gate_verdict = %s, gate_note = %s,"
            " gate_decided_by = %s, gate_decided_at = now() WHERE id = %s",
            (status, verdict, note, decided_by, message_id),
        )
        return self.get(message_id)


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


class PgUnitOfWork:
    def __init__(self, conn: Connection):
        self.agents = PgAgentRepo(conn)
        self.lines = PgLineRepo(conn)
        self.messages = PgMessageRepo(conn)
        self.channels = PgChannelRepo(conn)


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
