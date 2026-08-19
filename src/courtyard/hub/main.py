"""Hub entrypoint: assemble the FastAPI app, apply migrations, serve API + WebUI."""

from __future__ import annotations

import contextlib
import logging

import psycopg
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from courtyard.hub.api import router
from courtyard.hub.config import Config, load_config
from courtyard.hub.core.board import Board
from courtyard.hub.core.errors import DomainError
from courtyard.hub.core.gate import NoopApprover
from courtyard.hub.core.registry import Registry
from courtyard.hub.storage.postgres import PostgresStorage

logger = logging.getLogger("courtyard.hub")


def domain_error_handler(_request: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.http_status,
        content={"error": {"code": exc.code, "message": str(exc), **exc.extra}},
    )


def create_app(config: Config | None = None) -> FastAPI:
    cfg = config or load_config()

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        from courtyard.hub.storage.migrate import apply_migrations

        applied = apply_migrations(cfg.database_url)
        if applied:
            logger.info("migrations applied: %s", ", ".join(applied))
        storage = PostgresStorage(cfg.database_url)
        storage.open()
        registry = Registry(storage)
        registry.ensure_operator()
        app.state.storage = storage
        app.state.registry = registry
        app.state.board = Board(storage, registry, NoopApprover(), cfg.max_body_bytes)
        yield
        storage.close()

    app = FastAPI(title="Agent Courtyard", lifespan=lifespan)
    app.state.config = cfg
    app.add_exception_handler(DomainError, domain_error_handler)

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
