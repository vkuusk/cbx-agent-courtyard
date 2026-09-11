import logging

import pytest
from starlette.testclient import TestClient

from courtyard.hub.config import Config, NonLocalBindError, load_config
from courtyard.hub.main import AccessLog, configure_logging, startup_banner, startup_logger


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


def test_postgres_defaults_to_an_unusual_port():
    """Not 5432: a developer's own postgres lives there, and the hub must neither collide
    with it nor be mistaken for it. COURTYARD_PG_PORT still moves it."""
    assert (
        load_config(env={}).database_url
        == "postgresql://courtyard:courtyard@127.0.0.1:26432/courtyard"
    )
    assert load_config(env={"COURTYARD_PG_PORT": "5433"}).database_url.endswith(
        "@127.0.0.1:5433/courtyard"
    )


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


def test_startup_banner_says_where_how_and_how_loud():
    cfg = load_config(
        env={
            "DATABASE_URL": "postgresql://courtyard:secret@db.local:5433/yard",
            "COURTYARD_LOG_LEVEL": "warning",
            "COURTYARD_WEBUI_DIR": "/srv/webui",
        }
    )
    line = startup_banner(cfg)
    assert "http://127.0.0.1:2626" in line and "/srv/webui" in line
    assert "db.local:5433/yard" in line and "secret" not in line  # never the credentials
    assert "WARNING" in line and "only 4xx/5xx" in line  # silence from here on is health


def test_the_startup_line_shows_at_every_log_level(caplog):
    """His feedback (2026-09-08): with COURTYARD_LOG_LEVEL=WARNING `make run` printed
    nothing between uvicorn's launch and the first failing request, so a quiet hub and a
    hub that never came up looked the same. The ready line rides a logger pinned at INFO
    while every other hub logger follows the knob."""
    root = logging.getLogger()
    before = root.level
    try:
        configure_logging("WARNING")
        with caplog.at_level(logging.INFO, logger="courtyard.startup"):
            root.setLevel(logging.WARNING)  # what the operator's knob does to everything else
            startup_logger.info("ready")
            logging.getLogger("courtyard.hub").info("routine, must stay quiet")
            logging.getLogger("courtyard.hub").warning("a problem, must show")
        assert [r.getMessage() for r in caplog.records] == ["ready", "a problem, must show"]
    finally:
        root.setLevel(before)


def test_the_encoder_locality_check_leaves_the_bind_host_alone():
    """Found by review: the check reused the `host` variable, so an embeddings URL on
    `localhost` rebound the hub to `localhost` and a deliberate non-local bind was
    silently undone."""
    env = {"COURTYARD_EMBEDDINGS_URL": "http://localhost:11434/v1/embeddings"}
    assert load_config(env).host == "127.0.0.1"
    env.update(COURTYARD_HOST="0.0.0.0", COURTYARD_ALLOW_NONLOCAL_BIND="1")
    assert load_config(env).host == "0.0.0.0"
