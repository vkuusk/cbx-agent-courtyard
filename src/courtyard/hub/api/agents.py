"""Agent registry endpoints. Admin routes are unauthenticated in v1 (localhost trust, D3);
the inbox and peers routes are agent-scoped and require the agent's own bearer token."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from courtyard.common.models import Agent, AgentType, Message, PeersView
from courtyard.hub.api.deps import get_board, get_registry, require_agent
from courtyard.hub.core import install as install_core
from courtyard.hub.core.board import Board
from courtyard.hub.core.errors import InvalidToken, NotAllowed, WorkdirNotFound
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


@router.get("/{name_or_id}/peers")
def peers(
    name_or_id: str,
    caller: Annotated[Agent, Depends(require_agent)],
    registry: Annotated[Registry, Depends(get_registry)],
) -> PeersView:
    """Who the agent can talk to: reachable first, trimmed, rendered for the model (D14)."""
    agent = registry.get(name_or_id)
    if agent.id != caller.id:
        raise NotAllowed("token does not belong to this agent")
    return registry.peers(agent)


class InstallRequest(BaseModel):
    # The token is passed in (the hub never stores the plaintext), and verified to belong to
    # this agent before it is written into the file. workdir defaults to the agent's own.
    token: str
    workdir: str | None = None


class InstallResponse(BaseModel):
    path: str
    backed_up: str | None
    replaced_server: bool
    warning: str


@router.post("/{name_or_id}/install")
def install(
    name_or_id: str,
    body: InstallRequest,
    request: Request,
    registry: Annotated[Registry, Depends(get_registry)],
) -> InstallResponse:
    """Write the agent's `.mcp.json` into its workdir (dev mode; design §8/D8, 6d).

    Admin surface (localhost, D3). The caller proves it holds the agent's token by passing
    it — a wrong token is refused rather than written into a file that would never authenticate.
    """
    agent = registry.get(name_or_id)
    if registry.authenticate(body.token).id != agent.id:
        raise InvalidToken("that token does not belong to this agent")
    workdir = body.workdir or agent.workdir
    if not workdir:
        raise WorkdirNotFound(
            f"{agent.name} has no workdir set; add one when registering, or pass one here."
        )
    hub_url = str(request.base_url).rstrip("/")
    result = install_core.install(
        workdir, install_core.adapter_command(), hub_url, agent.name, body.token
    )
    return InstallResponse(**result.__dict__)


class UninstallRequest(BaseModel):
    workdir: str | None = None


class UninstallResponse(BaseModel):
    path: str
    restored_from_backup: bool
    removed_server: bool


@router.post("/{name_or_id}/uninstall")
def uninstall(
    name_or_id: str,
    body: UninstallRequest,
    registry: Annotated[Registry, Depends(get_registry)],
) -> UninstallResponse:
    """Reverse an install: restore the pre-install `.mcp.json`, or drop just our entry."""
    agent = registry.get(name_or_id)
    workdir = body.workdir or agent.workdir
    if not workdir:
        raise WorkdirNotFound(f"{agent.name} has no workdir set; pass one here.")
    result = install_core.uninstall(workdir)
    return UninstallResponse(**result.__dict__)
