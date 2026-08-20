"""HTTP API. Thin layer: routes validate input and call services; no domain logic here."""

import shutil
import sys
from pathlib import Path

from fastapi import APIRouter, Request

from courtyard.hub.api import agents, channels, events, gate, lines, operator

router = APIRouter(prefix="/api")


def _adapter_command() -> str:
    """Absolute path to the Claude Code adapter, for the copy-paste launch config (D8/L0).

    Claude Code spawns MCP servers with the *agent's* project as cwd, so a relative command
    or a `uv run` would not resolve. The hub knows where its own venv is; the WebUI does not.
    """
    beside_hub = Path(sys.executable).parent / "courtyard-claude-mcp"
    if beside_hub.exists():
        return str(beside_hub)
    found = shutil.which("courtyard-claude-mcp")
    return found or f"{sys.executable} -m courtyard.adapters.claude_code.mcp_server"


@router.get("/config")
def config() -> dict[str, str]:
    """What the WebUI needs to write an agent's launch configuration."""
    return {"adapter_command": _adapter_command()}


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
