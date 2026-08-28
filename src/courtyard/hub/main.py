"""Hub entrypoint: assemble the FastAPI app, apply migrations, serve API + WebUI."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime

import psycopg
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from courtyard.hub.api import router
from courtyard.hub.config import Config, load_config
from courtyard.hub.core.archive import Archiver
from courtyard.hub.core.board import Board
from courtyard.hub.core.channels import ChannelService
from courtyard.hub.core.deliver import Deliverer
from courtyard.hub.core.errors import DomainError
from courtyard.hub.core.events import EventBus
from courtyard.hub.core.gate import EventApprover
from courtyard.hub.core.registry import Registry
from courtyard.hub.core.shift import ShiftService
from courtyard.hub.storage.postgres import PostgresStorage

logger = logging.getLogger("courtyard.hub")


def domain_error_handler(_request: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.http_status,
        content={"error": {"code": exc.code, "message": str(exc), **exc.extra}},
    )


class RevalidatingStaticFiles(StaticFiles):
    """WebUI files change with every edit, and the browser loads them as modules that import
    each other. Without a cache header a normal reload can mix cached old modules with new
    ones. `no-cache` = always revalidate; the ETag makes that a cheap 304."""

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


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
        events = EventBus()
        events.bind(asyncio.get_running_loop())
        hub_started_at = datetime.now(UTC)  # one clock for liveness judging and the shift grace
        # The shift service owns the settings document; the services below read the
        # operator's discovery choice (§5.8, D22) through it at call time.
        shift = ShiftService(storage, events, cfg.heartbeat_seconds, hub_started_at=hub_started_at)

        def discovery() -> str:
            return shift.get_settings().discovery

        registry = Registry(storage, events, discovery=discovery)
        registry.ensure_operator()
        archiver = Archiver(storage, events)
        archiver.reconcile()  # lines of agents removed before archiving existed
        deliverer = Deliverer(storage, events, cfg.push_timeout)
        channels = ChannelService(
            storage,
            events,
            deliverer,
            cfg.heartbeat_seconds,
            cfg.gone_seconds,
            hub_started_at=hub_started_at,
            discovery=discovery,
        )
        channels.reset_unverified()  # D26: stored liveness is a claim until a beat proves it
        app.state.storage = storage
        app.state.events = events
        app.state.registry = registry
        app.state.channels = channels
        app.state.archiver = archiver
        app.state.shift = shift
        app.state.board = Board(
            storage,
            registry,
            EventApprover(events),
            cfg.max_body_bytes,
            events,
            deliverer,
            default_line_mode=lambda: shift.get_settings().default_line_mode,
            discovery=discovery,
        )

        async def sweep_liveness() -> None:
            while True:
                # D26: sweep fast while `unknown` statuses await judgement, so they
                # resolve within a second of the grace boundary.
                await asyncio.sleep(
                    min(cfg.sweep_seconds, 1.0) if channels.judging else cfg.sweep_seconds
                )
                try:
                    await asyncio.to_thread(channels.sweep)
                except Exception:
                    logger.exception("liveness sweep failed")

        async def tick_shift() -> None:
            # 1 s so the pill's countdown flips to spawning without a visible dead stop;
            # a tick outside `starting` is a lock-and-look, no database touched.
            while True:
                await asyncio.sleep(1)
                try:
                    await asyncio.to_thread(shift.tick)
                except Exception:
                    logger.exception("shift tick failed")

        sweeper = asyncio.create_task(sweep_liveness())
        shift_ticker = asyncio.create_task(tick_shift())
        yield
        for task in (sweeper, shift_ticker):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        deliverer.close()
        storage.close()

    app = FastAPI(title="Agent Courtyard", lifespan=lifespan)
    app.state.config = cfg
    app.add_exception_handler(DomainError, domain_error_handler)

    async def db_ping() -> None:
        async with await psycopg.AsyncConnection.connect(cfg.database_url) as conn:
            await conn.execute("SELECT 1")

    app.state.db_ping = db_ping
    app.include_router(router)

    app.mount("/", RevalidatingStaticFiles(directory=cfg.webui_dir, html=True), name="webui")
    return app


def cli() -> None:
    logging.basicConfig(level=logging.INFO)
    cfg = load_config()
    uvicorn.run(create_app(cfg), host=cfg.host, port=cfg.port)
