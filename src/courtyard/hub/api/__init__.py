"""HTTP API. Thin layer: routes validate input and call services; no domain logic here."""

from fastapi import APIRouter, Request

from courtyard.adapters.claude_code.mcp_server import INSTRUCTIONS
from courtyard.hub.api import agents, archive, channels, events, gate, lines, operator, shift
from courtyard.hub.core import envelope as envelope_core
from courtyard.hub.core.install import adapter_command

router = APIRouter(prefix="/api")


@router.get("/config")
def config() -> dict[str, str]:
    """What the WebUI needs to write an agent's launch configuration."""
    return {"adapter_command": adapter_command()}


@router.get("/envelope")
def envelope() -> list[dict[str, str | int]]:
    """Item 29 (visibility): every model-facing text, for the Admin page. The envelope
    variants come from the same render() that wraps real deliveries; the last block is
    the adapter's once-per-session instructions."""
    return [
        *envelope_core.preview(),
        {
            "title": "The adapter instructions",
            "note": "given to the session once, when the courtyard MCP server connects",
            "text": INSTRUCTIONS,
            "overhead_tokens": envelope_core.estimate_tokens(INSTRUCTIONS),
        },
    ]


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
router.include_router(shift.router)
