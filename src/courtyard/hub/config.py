"""Hub configuration. All settings come from environment variables with safe defaults."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}

DEFAULT_DATABASE_URL = "postgresql://courtyard:courtyard@127.0.0.1:5432/courtyard"


class NonLocalBindError(Exception):
    """Raised when configuration asks for a non-localhost bind without the explicit override."""


@dataclass(frozen=True)
class Config:
    host: str
    port: int
    database_url: str
    webui_dir: Path
    max_body_bytes: int


def _default_webui_dir() -> Path:
    # repo layout: src/courtyard/hub/config.py -> repo root / webui
    return Path(__file__).resolve().parents[3] / "webui"


def load_config(env: Mapping[str, str] | None = None) -> Config:
    env = os.environ if env is None else env
    host = env.get("COURTYARD_HOST", "127.0.0.1")
    if host not in LOCAL_HOSTS and env.get("COURTYARD_ALLOW_NONLOCAL_BIND") != "1":
        raise NonLocalBindError(
            f"refusing to bind {host!r}: courtyard v1 is a localhost-only service "
            "(design doc, security model). Set COURTYARD_ALLOW_NONLOCAL_BIND=1 to override."
        )
    return Config(
        host=host,
        port=int(env.get("COURTYARD_PORT", "2626")),
        database_url=env.get("DATABASE_URL", DEFAULT_DATABASE_URL),
        webui_dir=Path(env.get("COURTYARD_WEBUI_DIR", str(_default_webui_dir()))),
        max_body_bytes=int(env.get("COURTYARD_MAX_BODY_BYTES", "16384")),
    )
