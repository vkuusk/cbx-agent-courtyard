"""The database's identity (D38): the hub stamps the database it starts with and refuses
to keep serving when another database answers on the same port.

Seen live 2026-09-11: an installed hub's postgres was stopped; a dev checkout brought a
different compose project's postgres up on the same host port; the installed hub's pool
reconnected and served the fresh dev database as its own for an hour."""

from __future__ import annotations

import psycopg
from fastapi.testclient import TestClient

from courtyard.hub.main import create_app
from courtyard.hub.storage.postgres import IDENTITY_KEY


def stored_identity(config) -> str:
    with psycopg.connect(config.database_url) as conn:
        (value,) = conn.execute(
            "SELECT value FROM settings WHERE key = %s", (IDENTITY_KEY,)
        ).fetchone()
    return value


def test_the_hub_stamps_the_database_once_and_adopts_it_on_restart(client, config):
    first = client.app.state.storage.identity
    assert first and stored_identity(config) == first
    with TestClient(create_app(config)) as again:  # a restart, or another checkout's hub
        assert again.app.state.storage.identity == first
        assert again.get("/api/health").json()["db"] == "ok"


def test_a_swapped_database_is_refused_until_restart(client, config):
    assert client.get("/api/agents").status_code == 200
    with psycopg.connect(config.database_url, autocommit=True) as conn:
        # what the pool sees after a reconnect to a different compose project's postgres
        conn.execute(
            "UPDATE settings SET value = %s WHERE key = %s", ('"someone-else"', IDENTITY_KEY)
        )
    resp = client.get("/api/agents")
    assert resp.status_code == 503, resp.text
    assert resp.json()["error"]["code"] == "foreign_database"
    assert "not the one this hub started with" in resp.json()["error"]["message"]
    health = client.get("/api/health").json()
    assert health["db"].startswith("error:") and "identity" in health["db"]
    # sticky: putting the row back does not un-refuse; only a restart adopts a database
    with psycopg.connect(config.database_url, autocommit=True) as conn:
        conn.execute(
            "UPDATE settings SET value = %s WHERE key = %s",
            (psycopg.types.json.Json(client.app.state.storage.identity), IDENTITY_KEY),
        )
    assert client.get("/api/agents").status_code == 503
    with TestClient(create_app(config)) as restarted:
        assert restarted.get("/api/agents").status_code == 200


def test_health_alone_notices_the_swap(client, config):
    """The tray and the install poll only /api/health; it must not say ok over a
    database the hub would refuse to serve."""
    with psycopg.connect(config.database_url, autocommit=True) as conn:
        conn.execute("UPDATE settings SET value = %s WHERE key = %s", ('"other"', IDENTITY_KEY))
    assert client.get("/api/health").json()["db"].startswith("error:")
    assert client.get("/api/agents").status_code == 503
