"""Agent registry endpoints. Admin routes are unauthenticated in v1 (localhost trust, D3);
the inbox and peers routes are agent-scoped and require the agent's own bearer token."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from courtyard.common.models import Agent, AgentColor, AgentType, Message, PeersView
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
    color: AgentColor | None = None  # omitted = the hub picks the least-used colour
    # the model its runtime should use (feedback item 1); install writes it into the
    # agent's settings and the launch command shows it
    model: str | None = Field(default=None, max_length=120)


class AgentCreated(BaseModel):
    agent: Agent
    token: str  # also kept by the hub (D19): readable again via GET …/token


@router.post("", status_code=201)
def create_agent(
    body: AgentCreate, registry: Annotated[Registry, Depends(get_registry)]
) -> AgentCreated:
    agent, token = registry.create(
        body.name,
        body.type,
        body.description,
        body.sme_domain,
        body.workdir,
        body.launch,
        body.color,
        body.model,
    )
    return AgentCreated(agent=agent, token=token)


@router.get("")
def list_agents(registry: Annotated[Registry, Depends(get_registry)]) -> list[Agent]:
    return registry.list()


@router.get("/{name_or_id}")
def get_agent(name_or_id: str, registry: Annotated[Registry, Depends(get_registry)]) -> Agent:
    return registry.get(name_or_id)


class AgentPatch(BaseModel):
    """WP-D (item 8): the operator-editable fields. Absent = untouched; explicit null =
    cleared. Name and type are permanent identities and cannot be edited — an attempt is
    a schema error, never silently ignored."""

    model_config = ConfigDict(extra="forbid")

    description: str | None = Field(default=None, max_length=500)
    sme_domain: str | None = Field(default=None, max_length=120)
    workdir: str | None = None
    model: str | None = Field(default=None, max_length=120)
    color: AgentColor | None = None


@router.patch("/{name_or_id}")
def update_agent(
    name_or_id: str,
    body: AgentPatch,
    registry: Annotated[Registry, Depends(get_registry)],
) -> Agent:
    return registry.update(name_or_id, body.model_dump(exclude_unset=True))


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


class TokenView(BaseModel):
    token: str


@router.get("/{name_or_id}/token")
def token(name_or_id: str, registry: Annotated[Registry, Depends(get_registry)]) -> TokenView:
    """The agent's stored token, so the launch config can be opened again (D19)."""
    return TokenView(token=registry.token_of(name_or_id))


@router.post("/{name_or_id}/token", status_code=201)
def rotate_token(
    name_or_id: str, registry: Annotated[Registry, Depends(get_registry)]
) -> AgentCreated:
    """Replace the agent's token; the old one stops working immediately (D19)."""
    agent, new = registry.rotate_token(name_or_id)
    return AgentCreated(agent=agent, token=new)


class InstallRequest(BaseModel):
    # The hub keeps the token (D19), so none need be passed; one that is passed must belong
    # to this agent before it is written into the file. workdir defaults to the agent's own.
    token: str | None = None
    workdir: str | None = None


class InstallResponse(BaseModel):
    path: str
    backed_up: str | None
    replaced_server: bool
    settings_path: str  # .claude/settings.local.json: allow rule, model, status line (WP-A)
    settings_backed_up: str | None
    script_path: str  # start-with-courtyard.sh, the human launch wrapper (item 35)
    script_backed_up: str | None
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
    if body.token is None:
        token = registry.token_of(agent.name)
    elif registry.authenticate(body.token).id != agent.id:
        raise InvalidToken("that token does not belong to this agent")
    else:
        token = body.token
    workdir = body.workdir or agent.workdir
    if not workdir:
        raise WorkdirNotFound(
            f"{agent.name} has no workdir set; add one when registering, or pass one here."
        )
    hub_url = str(request.base_url).rstrip("/")
    result = install_core.install(
        workdir, install_core.adapter_command(), hub_url, agent.name, token, agent.model
    )
    return InstallResponse(**result.__dict__)


class UninstallRequest(BaseModel):
    workdir: str | None = None


class UninstallResponse(BaseModel):
    path: str
    restored_from_backup: bool
    removed_server: bool
    settings_restored: bool
    settings_cleaned: bool
    script_restored: bool
    script_removed: bool


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
