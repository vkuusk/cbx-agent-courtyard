"""Agent registry endpoints. Admin routes are unauthenticated in v1 (localhost trust, D3);
the inbox is agent-scoped and requires the agent's own bearer token."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from courtyard.common.models import Agent, AgentType, Message
from courtyard.hub.api.deps import get_board, get_registry, require_agent
from courtyard.hub.core.board import Board
from courtyard.hub.core.errors import NotAllowed
from courtyard.hub.core.registry import Registry

router = APIRouter(prefix="/agents", tags=["agents"])


class AgentCreate(BaseModel):
    name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
    type: AgentType
    description: str | None = Field(default=None, max_length=500)
    # what this agent OWNS — drives authority grading (design §7.5); short on purpose
    sme_domain: str | None = Field(default=None, max_length=120)
    workdir: str | None = None
    launch: dict[str, Any] | None = None


class AgentCreated(BaseModel):
    agent: Agent
    token: str  # shown exactly once


@router.post("", status_code=201)
def create_agent(
    body: AgentCreate, registry: Annotated[Registry, Depends(get_registry)]
) -> AgentCreated:
    agent, token = registry.create(
        body.name, body.type, body.description, body.sme_domain, body.workdir, body.launch
    )
    return AgentCreated(agent=agent, token=token)


@router.get("")
def list_agents(registry: Annotated[Registry, Depends(get_registry)]) -> list[Agent]:
    return registry.list()


@router.get("/{name_or_id}")
def get_agent(name_or_id: str, registry: Annotated[Registry, Depends(get_registry)]) -> Agent:
    return registry.get(name_or_id)


@router.delete("/{name_or_id}")
def remove_agent(name_or_id: str, registry: Annotated[Registry, Depends(get_registry)]) -> Agent:
    return registry.remove(name_or_id)


@router.get("/{name_or_id}/inbox")
def inbox(
    name_or_id: str,
    caller: Annotated[Agent, Depends(require_agent)],
    registry: Annotated[Registry, Depends(get_registry)],
    board: Annotated[Board, Depends(get_board)],
) -> list[Message]:
    """Return the agent's queued messages and mark them delivered (the pull path)."""
    agent = registry.get(name_or_id)
    if agent.id != caller.id:
        raise NotAllowed("token does not belong to this agent")
    return board.inbox(agent)
