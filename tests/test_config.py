import logging

import pytest
from starlette.testclient import TestClient

from courtyard.hub.config import Config, NonLocalBindError, load_config
from courtyard.hub.main import AccessLog


def test_defaults_are_localhost():
    cfg = load_config(env={})
    assert isinstance(cfg, Config)
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 2626


def test_refuses_nonlocal_bind_without_override():
    with pytest.raises(NonLocalBindError):
        load_config(env={"COURTYARD_HOST": "0.0.0.0"})


def test_nonlocal_bind_with_explicit_override():
    cfg = load_config(env={"COURTYARD_HOST": "0.0.0.0", "COURTYARD_ALLOW_NONLOCAL_BIND": "1"})
    assert cfg.host == "0.0.0.0"


def test_env_overrides():
    cfg = load_config(env={"COURTYARD_PORT": "3000", "DATABASE_URL": "postgresql://x/y"})
    assert cfg.port == 3000
    assert cfg.database_url == "postgresql://x/y"


def test_log_level_default_and_override():
    assert load_config(env={}).log_level == "INFO"
    # case-insensitive, stored upper (it feeds logging and uvicorn)
    assert load_config(env={"COURTYARD_LOG_LEVEL": "warning"}).log_level == "WARNING"
    with pytest.raises(ValueError, match="COURTYARD_LOG_LEVEL"):
        load_config(env={"COURTYARD_LOG_LEVEL": "verbose"})


def test_access_log_severity_follows_the_status(caplog):
    """His feedback: uvicorn logged a 422 at INFO. The replacement logs a request line
    at its real severity — below 400 INFO, 4xx WARNING, 5xx ERROR — so LOG_LEVEL=WARNING
    keeps failures visible while the routine lines go quiet."""

    async def stub(scope, receive, send):
        status = int(scope["path"].strip("/"))
        await send({"type": "http.response.start", "status": status, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    client = TestClient(AccessLog(stub))
    with caplog.at_level(logging.INFO, logger="courtyard.access"):
        client.get("/200?probe=1")
        client.post("/422")
        client.get("/500")
    by_status = {r.getMessage().rsplit(" ", 1)[-1]: r for r in caplog.records}
    assert by_status["200"].levelno == logging.INFO
    assert by_status["422"].levelno == logging.WARNING
    assert by_status["500"].levelno == logging.ERROR
    # the line keeps the shape uvicorn used: client - "METHOD target HTTP/x" status
    assert '- "GET /200?probe=1 HTTP/1.1" 200' in by_status["200"].getMessage()
    assert '- "POST /422 HTTP/1.1" 422' in by_status["422"].getMessage()
