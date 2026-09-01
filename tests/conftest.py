"""Shared fixtures. Integration tests run against a dedicated `courtyard_test` database in
the compose postgres (`make db-up`; `make test` brings it up automatically), so dev data in
the `courtyard` database is never touched."""

from __future__ import annotations

import socket
import threading
import time
from dataclasses import replace

import psycopg
import pytest
import uvicorn
from fastapi.testclient import TestClient

from courtyard.hub.config import load_config
from courtyard.hub.main import create_app
from courtyard.hub.storage.migrate import apply_migrations

TEST_DB = "courtyard_test"


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


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
        conn.execute("TRUNCATE agents, lines, messages, channels, lines_archive, settings CASCADE")
    # TestClient as a context manager runs the lifespan (migrations + operator bootstrap).
    with TestClient(create_app(config)) as c:
        yield c


@pytest.fixture()
def live_hub(config):
    """Factory for a real uvicorn hub on an ephemeral port (step-2 integration tests
    exercise actual HTTP end-to-end: hub pushes to real dummy listeners)."""
    with psycopg.connect(config.database_url, autocommit=True) as conn:
        conn.execute("TRUNCATE agents, lines, messages, channels, lines_archive, settings CASCADE")
    running: list[tuple[uvicorn.Server, threading.Thread]] = []

    def _start(**overrides) -> str:
        cfg = replace(config, port=_free_port(), **overrides)
        server = uvicorn.Server(
            uvicorn.Config(create_app(cfg), host=cfg.host, port=cfg.port, log_level="warning")
        )
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        deadline = time.monotonic() + 15
        while not server.started:
            if time.monotonic() > deadline:
                raise RuntimeError("test hub failed to start")
            time.sleep(0.02)
        running.append((server, thread))
        return f"http://127.0.0.1:{cfg.port}"

    yield _start
    for server, thread in running:
        server.should_exit = True
        thread.join(timeout=10)


@pytest.fixture()
def make_agent(client):
    def _make(name: str, type: str = "dummy", description: str | None = None):
        resp = client.post(
            "/api/agents", json={"name": name, "type": type, "description": description}
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        return data["agent"], data["token"]

    return _make
