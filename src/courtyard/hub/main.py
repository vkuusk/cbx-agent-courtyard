"""Hub entrypoint: assemble the FastAPI app, apply migrations, serve API + WebUI."""

from __future__ import annotations

import contextlib
import logging

import psycopg
import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from courtyard.hub.api import router
from courtyard.hub.config import Config, load_config

logger = logging.getLogger("courtyard.hub")


def create_app(config: Config | None = None) -> FastAPI:
    cfg = config or load_config()

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):
        from courtyard.hub.storage.migrate import apply_migrations

        applied = apply_migrations(cfg.database_url)
        if applied:
            logger.info("migrations applied: %s", ", ".join(applied))
        yield

    app = FastAPI(title="Agent Courtyard", lifespan=lifespan)
    app.state.config = cfg

    async def db_ping() -> None:
        async with await psycopg.AsyncConnection.connect(cfg.database_url) as conn:
            await conn.execute("SELECT 1")

    app.state.db_ping = db_ping
    app.include_router(router)
    app.mount("/", StaticFiles(directory=cfg.webui_dir, html=True), name="webui")
    return app


def cli() -> None:
    logging.basicConfig(level=logging.INFO)
    cfg = load_config()
    uvicorn.run(create_app(cfg), host=cfg.host, port=cfg.port)
