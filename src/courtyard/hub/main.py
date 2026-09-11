"""Hub entrypoint: assemble the FastAPI app, apply migrations, serve API + WebUI."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime
from urllib.parse import urlsplit

import psycopg
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from courtyard.hub.api import router
from courtyard.hub.config import DEFAULT_PG_PORT, Config, load_config
from courtyard.hub.core.archive import Archiver
from courtyard.hub.core.board import Board
from courtyard.hub.core.channels import ChannelService
from courtyard.hub.core.deliver import Deliverer
from courtyard.hub.core.encoder import encoder_from_config
from courtyard.hub.core.errors import DomainError
from courtyard.hub.core.events import EventBus
from courtyard.hub.core.gate import EventApprover
from courtyard.hub.core.memory import Memory
from courtyard.hub.core.registry import Registry
from courtyard.hub.core.shift import ShiftService
from courtyard.hub.core.teams import TeamService
from courtyard.hub.storage.postgres import PostgresStorage

logger = logging.getLogger("courtyard.hub")
# The one line that shows at EVERY COURTYARD_LOG_LEVEL (his feedback, 2026-09-08): under
# WARNING the hub used to start in silence, and the operator could not tell a quiet hub
# from one that never came up. configure_logging pins this logger at INFO.
startup_logger = logging.getLogger("courtyard.startup")


def domain_error_handler(_request: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.http_status,
        content={"error": {"code": exc.code, "message": str(exc), **exc.extra}},
    )


access_logger = logging.getLogger("courtyard.access")


class AccessLog:
    """Access log with honest severity. uvicorn logs every request line at INFO, error
    responses included; here a 4xx logs as WARNING and a 5xx as ERROR, so
    COURTYARD_LOG_LEVEL=WARNING keeps failures visible while routine 200 lines go
    quiet. A pure ASGI pass-through that only watches `http.response.start` — it never
    wraps the response body, so SSE keeps streaming (the middleware lesson from the
    static-files days). Applied around the app in `cli()`, replacing uvicorn's access
    log; tests build the bare FastAPI app and log nothing, as before."""

    def __init__(self, app):
        self._app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        async def sending(message):
            if message["type"] == "http.response.start":
                status = message["status"]
                level = (
                    logging.ERROR
                    if status >= 500
                    else logging.WARNING
                    if status >= 400
                    else logging.INFO
                )
                client = scope.get("client") or ("-", 0)
                query = scope.get("query_string", b"").decode()
                target = scope["path"] + (f"?{query}" if query else "")
                access_logger.log(
                    level,
                    '%s:%s - "%s %s HTTP/%s" %s',
                    client[0],
                    client[1],
                    scope["method"],
                    target,
                    scope.get("http_version", "1.1"),
                    status,
                )
            await send(message)

        await self._app(scope, receive, sending)


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
        from courtyard.hub.storage.migrate import ForeignDatabaseError, apply_migrations

        try:
            applied = apply_migrations(cfg.database_url)
        except ForeignDatabaseError as exc:
            logger.error("%s", exc)
            raise
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
            # item 34 (D30): a session beginning during an active shift gets a delivery check
            shift_active=lambda: shift.status().state in ("starting", "on"),
            verify_timeout=cfg.verify_timeout,
        )
        channels.begin_verification()  # D26: stored liveness is a claim until a beat proves it
        shift.bind_verifier(channels.begin_verification)  # D28: shift start re-verifies too
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
            thread_budget=lambda: shift.get_settings().thread_budget,
        )
        # Hub memory (hub-memory.md): recall reads through the same settings and discovery
        # dial as the board; the case files themselves are written by the board at close.
        encoder = encoder_from_config(cfg)
        app.state.memory = Memory(
            storage,
            registry,
            settings=shift.get_settings,
            events=events,
            deliverer=deliverer,
            discovery=discovery,
            encoder=encoder,
        )
        # Projection (D33) registers agents and links lines through the same services the
        # operator's own gestures use, so events and invariants come along for free.
        app.state.teams = TeamService(
            storage,
            registry=registry,
            board=app.state.board,
            shift_active=lambda: shift.status().state != "off",
            set_discovery=lambda v: shift.update_settings({"discovery": v}),
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

        async def embed_memory() -> None:
            # hub memory (hub-memory.md section 7): records get their vector after the
            # fact, in batches, so a slow or absent encoder never holds up a thread close
            while True:
                try:
                    done = await asyncio.to_thread(app.state.memory.embed_pending)
                except Exception:
                    logger.exception("memory embedding sweep failed")
                    done = 0
                await asyncio.sleep(1.0 if done else cfg.embed_sweep_seconds)

        sweeper = asyncio.create_task(sweep_liveness())
        shift_ticker = asyncio.create_task(tick_shift())
        embedder = asyncio.create_task(embed_memory()) if encoder.name != "none" else None
        startup_logger.info(startup_banner(cfg))
        yield
        for task in (sweeper, shift_ticker, embedder):
            if task is None:
                continue
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        deliverer.close()
        storage.close()

    # The interactive API reference (Swagger UI) lives under /api like everything the
    # hub serves programmatically; "try it out" works against this very hub, and the
    # Authorize button takes an agent's token for the agent-scoped routes.
    app = FastAPI(
        title="Agent Courtyard",
        description=(
            "The hub's HTTP API. Admin routes are open on localhost (D3); agent-scoped "
            "routes (`/api/agents/{name}/...`, `/api/lines/send`, ...) take the agent's "
            "bearer token: press Authorize and paste the token from the agent's launch config."
        ),
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )
    app.state.config = cfg
    app.add_exception_handler(DomainError, domain_error_handler)

    async def db_ping() -> None:
        async with await psycopg.AsyncConnection.connect(cfg.database_url) as conn:
            await conn.execute("SELECT 1")

    app.state.db_ping = db_ping
    app.include_router(router)

    app.mount("/", RevalidatingStaticFiles(directory=cfg.webui_dir, html=True), name="webui")
    return app


def startup_banner(cfg: Config) -> str:
    """What the operator needs to see once the hub is up: where it listens, what it
    serves and talks to, and how loud it is going to be from here on (so a WARNING
    hub's silence reads as health, not as a hang). The database URL loses its
    credentials; the rest of it says which postgres this hub is on."""
    db = urlsplit(cfg.database_url)
    where = f"{db.hostname or 'localhost'}:{db.port or DEFAULT_PG_PORT}{db.path}"
    quiet = {
        "DEBUG": "everything shows",
        "INFO": "routine request lines show",
        "WARNING": "only 4xx/5xx request lines and problems show",
        "ERROR": "only 5xx request lines and errors show",
    }[cfg.log_level]
    similarity = (
        f"similarity via {cfg.embeddings_model} at {cfg.embeddings_url}"
        if cfg.embeddings_url
        else "recall is full-text only (no COURTYARD_EMBEDDINGS_URL)"
    )
    return (
        f"courtyard hub ready on http://{cfg.host}:{cfg.port} (webui {cfg.webui_dir}, "
        f"postgres {where}; {similarity}); log level {cfg.log_level}: {quiet}"
    )


def configure_logging(level: str) -> None:
    """One knob for stdout verbosity (COURTYARD_LOG_LEVEL): the hub's own loggers via
    the root config, uvicorn's via its log_level (see cli). The startup logger is pinned
    at INFO so its ready line shows whatever the knob says."""
    logging.basicConfig(level=level)
    startup_logger.setLevel(logging.INFO)


# How long a stopping hub waits for open connections before closing them. The WebUI holds
# its event stream open for as long as the page lives, so without a bound a SIGTERM (the
# Admin page's restart, `launchctl kickstart -k`, a bootout) leaves the old process
# waiting on that stream: not serving, not exiting, and under launchd never restarted.
GRACEFUL_SHUTDOWN_SECONDS = 3


def server_config(cfg: Config, **overrides: object) -> uvicorn.Config:
    """The uvicorn configuration the hub runs with; the test suite runs the same one."""
    options: dict[str, object] = {
        "host": cfg.host,
        "port": cfg.port,
        "log_level": cfg.log_level.lower(),
        # uvicorn's access log is replaced by AccessLog so error responses carry their
        # real severity instead of INFO
        "access_log": False,
        "timeout_graceful_shutdown": GRACEFUL_SHUTDOWN_SECONDS,
    }
    options.update(overrides)
    return uvicorn.Config(AccessLog(create_app(cfg)), **options)


def cli() -> None:
    cfg = load_config()
    configure_logging(cfg.log_level)
    uvicorn.Server(server_config(cfg)).run()
