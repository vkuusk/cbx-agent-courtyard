import pytest

from courtyard.hub.config import Config, NonLocalBindError, load_config


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
