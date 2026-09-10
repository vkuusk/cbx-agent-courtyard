import psycopg
import pytest

from courtyard.hub.storage.migrate import apply_migrations, migration_files

EXPECTED_TABLES = {"schema_migrations", "agents", "lines", "messages", "threads", "channels"}


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


def test_the_hub_refuses_to_create_its_schema_in_somebody_elses_database(config):
    """A postgres that answers on the configured port but is not the hub's: tables that
    are not ours in an unmigrated database mean stop, never migrate. A database the hub
    already migrated may hold extra tables (an operator's own) and stays fine."""
    from courtyard.hub.storage.migrate import ForeignDatabaseError

    admin_url = config.database_url.rsplit("/", 1)[0] + "/postgres"
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute("DROP DATABASE IF EXISTS courtyard_foreign WITH (FORCE)")
        conn.execute("CREATE DATABASE courtyard_foreign")
    foreign_url = config.database_url.rsplit("/", 1)[0] + "/courtyard_foreign"
    try:
        with psycopg.connect(foreign_url, autocommit=True) as conn:
            conn.execute("CREATE TABLE invoices (id int)")
        with pytest.raises(ForeignDatabaseError, match="invoices"):
            apply_migrations(foreign_url)
        with psycopg.connect(foreign_url) as conn:
            assert conn.execute("SELECT to_regclass('public.agents')").fetchone()[0] is None
        # an empty database is ours to migrate
        with psycopg.connect(foreign_url, autocommit=True) as conn:
            conn.execute("DROP TABLE invoices")
        assert apply_migrations(foreign_url)
        # once migrated, extra tables beside ours are nobody's business
        with psycopg.connect(foreign_url, autocommit=True) as conn:
            conn.execute("CREATE TABLE operator_notes_of_my_own (id int)")
        assert apply_migrations(foreign_url) == []
    finally:
        with psycopg.connect(admin_url, autocommit=True) as conn:
            conn.execute("DROP DATABASE IF EXISTS courtyard_foreign WITH (FORCE)")
