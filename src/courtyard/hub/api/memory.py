"""Hub memory endpoints (design hub-memory.md, slice 1).

Two doors onto one store. `/api/memory` is the admin surface (D3, localhost): the
Memory page and every other consumer read trimmed records and full case files here.
`/api/agents/{me}/recall` is the agent's door, behind its bearer token: the same
records, filtered by what the agent may see, with the model-facing text rendered by
the hub (D14) so the `courtyard_recall` tool in either adapter only forwards it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from courtyard.common.models import Agent, MemoryRecord, RecallView
from courtyard.hub.api.deps import get_memory, get_registry, require_agent
from courtyard.hub.core.errors import NotAllowed
from courtyard.hub.core.memory import Memory
from courtyard.hub.core.registry import Registry

router = APIRouter(tags=["memory"])


@router.get("/memory")
def search_memory(
    memory: Annotated[Memory, Depends(get_memory)],
    q: str | None = None,
    participant: str | None = None,
    line: UUID | None = None,
    since: datetime | None = None,
    limit: Annotated[int | None, Query(ge=1, le=20)] = None,
) -> list[MemoryRecord]:
    """Trimmed records: best match first with a question, newest first without."""
    return memory.search(
        question=q, participant=participant, line_id=line, since=since, limit=limit
    )


@router.get("/memory/count")
def count_memory(memory: Annotated[Memory, Depends(get_memory)]) -> dict[str, int]:
    return {"count": memory.count()}


@router.get("/memory/{record_id}")
def get_memory_record(
    record_id: UUID, memory: Annotated[Memory, Depends(get_memory)]
) -> MemoryRecord:
    """One record with its full case file."""
    return memory.get(record_id)


@router.get("/agents/{name_or_id}/recall")
def recall(
    name_or_id: str,
    caller: Annotated[Agent, Depends(require_agent)],
    registry: Annotated[Registry, Depends(get_registry)],
    memory: Annotated[Memory, Depends(get_memory)],
    q: str = "",
    limit: Annotated[int | None, Query(ge=1, le=20)] = None,
) -> RecallView:
    """The `courtyard_recall` tool: what the team has settled before, as far as this
    agent may see it, trimmed and bounded, rendered for the model."""
    agent = registry.get(name_or_id)
    if agent.id != caller.id:
        raise NotAllowed("token does not belong to this agent")
    return memory.recall(agent, q, limit)


@router.get("/agents/{name_or_id}/recall/{record_id}")
def recall_case(
    name_or_id: str,
    record_id: UUID,
    caller: Annotated[Agent, Depends(require_agent)],
    registry: Annotated[Registry, Depends(get_registry)],
    memory: Annotated[Memory, Depends(get_memory)],
) -> MemoryRecord:
    """One full case file, by the handle a recall listing gave, rendered for the model."""
    agent = registry.get(name_or_id)
    if agent.id != caller.id:
        raise NotAllowed("token does not belong to this agent")
    return memory.recall_case(agent, record_id)
