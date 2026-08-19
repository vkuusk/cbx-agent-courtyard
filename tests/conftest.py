"""Shared fixtures. Integration tests need the compose postgres: `make db-up` (make test does it)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from courtyard.hub.config import load_config
from courtyard.hub.main import create_app


@pytest.fixture(scope="session")
def config():
    return load_config()


@pytest.fixture()
def client(config):
    # TestClient as a context manager runs the lifespan (migrations against the dev DB).
    with TestClient(create_app(config)) as c:
        yield c
