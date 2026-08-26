"""HTTP API. Thin layer: routes validate input and call services; no domain logic here."""

from fastapi import APIRouter, Request

from courtyard.hub.api import agents, archive, channels, events, gate, lines, operator, shift
from courtyard.hub.core.install import adapter_command

router = APIRouter(prefix="/api")


@router.get("/config")
def config() -> dict[str, str]:
    """What the WebUI needs to write an agent's launch configuration."""
    return {"adapter_command": adapter_command()}


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
