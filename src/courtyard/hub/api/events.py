"""SSE event stream: everything that changes on the board, as it changes.

Event types: `agent` (registration/liveness), `line` (state/mode), `message` (created or
status change), `gate` (a message awaits the operator). Data is the full fresh object —
consumers upsert by id and refetch on (re)connect, so a dropped event is never fatal.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

router = APIRouter(tags=["events"])

KEEPALIVE_SECONDS = 15


@router.get("/events")
async def events(request: Request) -> StreamingResponse:
    bus = request.app.state.events

    async def stream():
        queue = bus.subscribe()
        try:
            yield ": connected\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_SECONDS)
                except TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                yield f"event: {event['type']}\ndata: {json.dumps(event['data'])}\n\n"
        finally:
            bus.unsubscribe(queue)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
