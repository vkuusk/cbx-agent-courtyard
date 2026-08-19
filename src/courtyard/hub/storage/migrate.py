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


def apply_migrations(database_url: str) -> list[str]:
    """Apply pending migrations, each in its own transaction; return versions applied."""
    applied: list[str] = []
    with psycopg.connect(database_url, autocommit=True) as conn:
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
