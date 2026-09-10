"""Numbered SQL migrations, applied at hub startup. Each file runs exactly once."""

from __future__ import annotations

from importlib import resources

import psycopg


def migration_files() -> list[tuple[str, str]]:
    """Return (version, sql) pairs sorted by filename."""
    root = resources.files("courtyard.hub.storage") / "migrations"
    found = [
        (entry.name, entry.read_text()) for entry in root.iterdir() if entry.name.endswith(".sql")
    ]
    return sorted(found)


class ForeignDatabaseError(Exception):
    """The database already holds tables that are not the hub's: this is somebody else's
    postgres (a developer's own on the same port, a database with the same name), and the
    hub must not create its schema inside it."""


def foreign_tables(conn: psycopg.Connection) -> list[str]:
    """Tables in `public` on a database the hub has never migrated. Anything there means
    the database is not ours."""
    rows = conn.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
    ).fetchall()
    return [name for (name,) in rows if name != "schema_migrations"]


def apply_migrations(database_url: str) -> list[str]:
    """Apply pending migrations, each in its own transaction; return versions applied.

    On a database the hub has never touched, refuse if it already holds tables: the hub
    only ever creates its schema in an empty database (its own compose postgres), never
    inside a postgres that happens to answer on the configured port."""
    applied: list[str] = []
    with psycopg.connect(database_url, autocommit=True) as conn:
        fresh = conn.execute("SELECT to_regclass('public.schema_migrations') IS NULL").fetchone()[0]
        if fresh:
            strangers = foreign_tables(conn)
            if strangers:
                shown = ", ".join(strangers[:5]) + (" ..." if len(strangers) > 5 else "")
                raise ForeignDatabaseError(
                    f"refusing to create the hub's schema in a database that already holds "
                    f"other tables ({shown}). This is not the hub's postgres: check "
                    "COURTYARD_PG_PORT / DATABASE_URL, or point the hub at an empty database."
                )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " version text PRIMARY KEY,"
            " applied_at timestamptz NOT NULL DEFAULT now())"
        )
        rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
        done = {version for (version,) in rows}
        for version, sql in migration_files():
            if version in done:
                continue
            with conn.transaction():
                conn.execute(sql)
                conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))
            applied.append(version)
    return applied
