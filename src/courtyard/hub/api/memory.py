"""Hub memory endpoints (design hub-memory.md, slice 1).

Two doors onto one store. `/api/memory` is the admin surface (D3, localhost): the
Memory page and every other consumer read trimmed records and full case files here.
`/api/agents/{me}/recall` is the agent's door, behind its bearer token: the same
records, filtered by what the agent may see, with the model-facing text rendered by
the hub (D14) so the `courtyard_recall` tool in either adapter only forwards it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from courtyard.common.models import Agent, GateVerdict, MemoryRecord, MemoryScope, RecallView
from courtyard.hub.api.deps import get_memory, get_registry, require_agent
from courtyard.hub.core.errors import NotAllowed, NoteScopeUnclear
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
    mode: Literal["exact", "vector", "hybrid"] | None = None,
) -> list[MemoryRecord]:
    """Trimmed records: best match first with a question, newest first without. `mode`
    defaults to hybrid when an encoder is configured, exact (full text) otherwise; the
    recall tool never exposes it."""
    return memory.search(
        question=q, participant=participant, line_id=line, since=since, limit=limit, mode=mode
    )


@router.get("/memory/encoder")
def encoder_status(memory: Annotated[Memory, Depends(get_memory)]) -> dict:
    """Which encoder the hub uses, and how many records carry its vector."""
    return memory.encoder_status()


@router.post("/memory/embed")
def embed_now(memory: Annotated[Memory, Depends(get_memory)]) -> dict[str, int]:
    """Run one embedding pass now instead of waiting for the sweep (up to a batch)."""
    return {"embedded": memory.embed_pending()}


@router.get("/memory/count")
def count_memory(memory: Annotated[Memory, Depends(get_memory)]) -> dict[str, int]:
    return {"count": memory.count()}


@router.get("/memory/pending")
def pending_notes(memory: Annotated[Memory, Depends(get_memory)]) -> list[MemoryRecord]:
    """Agents' notes waiting for the operator's verdict, oldest first."""
    return memory.pending()


class OperatorNote(BaseModel):
    body: str = Field(min_length=1, max_length=2000)
    scope: MemoryScope = "team"
    line: UUID | None = None  # required when scope is `line`


@router.post("/memory/notes", status_code=201)
def operator_note(
    body: OperatorNote,
    registry: Annotated[Registry, Depends(get_registry)],
    memory: Annotated[Memory, Depends(get_memory)],
) -> MemoryRecord:
    """The operator's standing guidance: accepted at once, team-wide unless scoped."""
    operator = registry.get("operator")
    if body.scope == "line" and body.line is None:
        raise NoteScopeUnclear("a line-scoped note needs the line")
    return memory.note(operator, body.body, line_id=body.line, team_wide=body.scope == "team")


class NoteDecision(BaseModel):
    verdict: GateVerdict
    note: str | None = None


@router.post("/memory/{record_id}/decide")
def decide_note(
    record_id: UUID, body: NoteDecision, memory: Annotated[Memory, Depends(get_memory)]
) -> MemoryRecord:
    """Approve, return (with the comment) or drop a pending note."""
    return memory.decide(record_id, body.verdict, body.note)


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


class AgentNote(BaseModel):
    body: str = Field(min_length=1, max_length=2000)
    peer: str | None = None  # the line the note is for, named by the other agent
    team_wide: bool = False


@router.post("/agents/{name_or_id}/notes", status_code=201)
def agent_note(
    name_or_id: str,
    body: AgentNote,
    caller: Annotated[Agent, Depends(require_agent)],
    registry: Annotated[Registry, Depends(get_registry)],
    memory: Annotated[Memory, Depends(get_memory)],
) -> MemoryRecord:
    """The `courtyard_note` tool: deposit a lesson into the team's memory. Scoped to
    the line with `peer` (or the agent's only line) unless `team_wide`; waits at the
    gate when that line is supervised, and always when team-wide."""
    agent = registry.get(name_or_id)
    if agent.id != caller.id:
        raise NotAllowed("token does not belong to this agent")
    return memory.note(agent, body.body, peer=body.peer, team_wide=body.team_wide)


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
