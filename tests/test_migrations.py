import psycopg

from courtyard.hub.storage.migrate import apply_migrations, migration_files

EXPECTED_TABLES = {"schema_migrations", "agents", "lines", "messages", "channels"}


def test_migrations_are_idempotent(config):
    apply_migrations(config.database_url)
    assert apply_migrations(config.database_url) == []


def test_schema_tables_exist(config):
    apply_migrations(config.database_url)
    with psycopg.connect(config.database_url) as conn:
        rows = conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        ).fetchall()
    assert EXPECTED_TABLES <= {name for (name,) in rows}


def test_migration_files_are_ordered():
    versions = [version for version, _ in migration_files()]
    assert versions == sorted(versions)
    assert versions, "at least one migration must exist"
