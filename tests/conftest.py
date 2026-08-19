"""Shared fixtures. Integration tests run against a dedicated `courtyard_test` database in
the compose postgres (`make db-up`; `make test` brings it up automatically), so dev data in
the `courtyard` database is never touched."""

from __future__ import annotations

from dataclasses import replace

import psycopg
import pytest
from fastapi.testclient import TestClient

from courtyard.hub.config import load_config
from courtyard.hub.main import create_app
from courtyard.hub.storage.migrate import apply_migrations

TEST_DB = "courtyard_test"


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="session")
def config():
    base = load_config()
    with psycopg.connect(base.database_url, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
        conn.execute(f"CREATE DATABASE {TEST_DB}")
    test_url = base.database_url.rsplit("/", 1)[0] + f"/{TEST_DB}"
    apply_migrations(test_url)
    return replace(base, database_url=test_url)


@pytest.fixture()
def client(config):
    with psycopg.connect(config.database_url, autocommit=True) as conn:
        conn.execute("TRUNCATE agents, lines, messages, channels CASCADE")
    # TestClient as a context manager runs the lifespan (migrations + operator bootstrap).
    with TestClient(create_app(config)) as c:
        yield c


@pytest.fixture()
def make_agent(client):
    def _make(name: str, type: str = "puppet"):
        resp = client.post("/api/agents", json={"name": name, "type": type})
        assert resp.status_code == 201, resp.text
        data = resp.json()
        return data["agent"], data["token"]

    return _make
