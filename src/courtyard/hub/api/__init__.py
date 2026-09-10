"""HTTP API. Thin layer: routes validate input and call services; no domain logic here."""

import asyncio
import os
import signal
from pathlib import Path

from fastapi import APIRouter, Request

from courtyard.adapters.claude_code.mcp_server import INSTRUCTIONS
from courtyard.hub.api import (
    agents,
    archive,
    channels,
    events,
    gate,
    lines,
    memory,
    operator,
    shift,
    teams,
)
from courtyard.hub.core import envelope as envelope_core
from courtyard.hub.core import memory as memory_core
from courtyard.hub.core.errors import NotSupervised, WorkdirNotFound
from courtyard.hub.core.install import adapter_command

router = APIRouter(prefix="/api")


@router.get("/config")
def config() -> dict[str, str | bool]:
    """What the WebUI needs to write an agent's launch configuration, and whether a
    supervisor (launchd, `make install`) restarts the hub when it exits."""
    return {"adapter_command": adapter_command(), "supervised": supervised()}


def supervised() -> bool:
    return bool(os.environ.get("COURTYARD_SUPERVISED"))


def _exit_hub() -> None:
    """Ask uvicorn to shut down cleanly; under launchd's KeepAlive that is a restart."""
    os.kill(os.getpid(), signal.SIGTERM)


@router.post("/hub/restart", status_code=202)
async def restart_hub() -> dict[str, bool]:
    """The Admin page's restart button. Only under a supervisor: without one the hub would
    simply stop, so the request is refused instead (`not_supervised`)."""
    if not supervised():
        raise NotSupervised(
            "the hub is not running under a supervisor (make install); restarting would stop it"
        )
    asyncio.get_running_loop().call_later(0.5, _exit_hub)
    return {"restarting": True}


@router.get("/envelope")
def envelope() -> list[dict[str, str | int]]:
    """Item 29 (visibility): every model-facing text, for the Admin page. The envelope
    variants come from the same render() that wraps real deliveries; the last block is
    the adapter's once-per-session instructions."""
    recall_sample = memory_core.render_listing("vpc module ipv6", memory_core.sample_records())
    return [
        *envelope_core.preview(),
        {
            "title": "A recall listing",
            "note": (
                "what courtyard_recall returns for a question (hub-memory.md); bounded by "
                "Admin → Recall returns, each field cut to Recall trims to"
            ),
            "text": recall_sample,
            "overhead_tokens": envelope_core.estimate_tokens(recall_sample),
        },
        {
            "title": "The adapter instructions",
            "note": "given to the session once, when the courtyard MCP server connects",
            "text": INSTRUCTIONS,
            "overhead_tokens": envelope_core.estimate_tokens(INSTRUCTIONS),
        },
    ]


@router.post("/fs/pick-dir")
def fs_pick_dir(body: dict | None = None) -> dict:
    """Open the native macOS folder dialog on the hub's screen and return the chosen
    path ({"path": null} on cancel). Answers `native_picker_unavailable` where there is
    no such dialog — the WebUI then falls back to the /fs/dirs browse dialog."""
    from courtyard.hub.core.fs_pick import pick_directory

    prompt = (body or {}).get("prompt") or "Choose a directory for the courtyard"
    return {"path": pick_directory(str(prompt)[:200])}


@router.get("/fs/dirs")
def fs_dirs(path: str | None = None) -> dict:
    """Directory listing for the workdir picker (item 37). Dev-mode admin surface
    (D3, localhost-only): the hub shares the operator's disk, exactly the premise
    install already relies on. Directories only; hidden entries excluded; starts
    at the hub user's home when no path is given."""
    base = (Path(path).expanduser() if path else Path.home()).resolve()
    if not base.is_dir():
        raise WorkdirNotFound(f"{base} is not a directory the hub can see")
    dirs: list[str] = []
    try:
        for entry in sorted(base.iterdir(), key=lambda e: e.name.lower()):
            if entry.name.startswith("."):
                continue
            try:
                if entry.is_dir():
                    dirs.append(entry.name)
            except OSError:
                continue
    except PermissionError:
        raise WorkdirNotFound(f"the hub may not read {base}") from None
    parent = str(base.parent) if base.parent != base else None
    return {"path": str(base), "parent": parent, "dirs": dirs[:500]}


@router.get("/health")
async def health(request: Request) -> dict[str, str]:
    db = "ok"
    try:
        await request.app.state.db_ping()
    except Exception as exc:  # noqa: BLE001 - health must report any failure, not crash
        db = f"error: {exc}"
    return {"status": "ok", "db": db}


router.include_router(agents.router)
router.include_router(channels.router)
router.include_router(lines.router)
router.include_router(gate.router)
router.include_router(operator.router)
router.include_router(events.router)
router.include_router(archive.router)
router.include_router(memory.router)
router.include_router(shift.router)
router.include_router(teams.router)
