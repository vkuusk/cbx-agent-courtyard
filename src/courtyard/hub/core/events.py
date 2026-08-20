"""In-process event bus bridging the sync domain code to async SSE subscribers.

Domain services publish from worker threads (FastAPI runs sync routes in a threadpool);
subscribers are async generators on the event loop. Events are advisory — the UI refetches
on (re)connect — so a slow subscriber's overflowing queue drops events rather than blocking
the domain.
"""

from __future__ import annotations

import asyncio
import logging

from pydantic import BaseModel

logger = logging.getLogger("courtyard.hub")

_QUEUE_SIZE = 256


class EventBus:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queues: set[asyncio.Queue] = set()

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def publish(self, type_: str, model: BaseModel) -> None:
        """Thread-safe; a no-op before bind() (e.g. in scripts using the services directly)."""
        if self._loop is None or self._loop.is_closed():
            return
        event = {"type": type_, "data": model.model_dump(mode="json")}
        try:
            self._loop.call_soon_threadsafe(self._fanout, event)
        except RuntimeError:  # loop shut down between the check and the call
            pass

    def _fanout(self, event: dict) -> None:
        for queue in self._queues:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("SSE subscriber too slow; dropping a %s event", event["type"])

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_SIZE)
        self._queues.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._queues.discard(queue)
