"""Channel endpoints: the adapter contract's attach / heartbeat / detach (design §7.1).

All three are agent-scoped: the bearer token identifies the caller, and the path agent
must be the caller itself.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from courtyard.common.models import Agent, AttachSummary
from courtyard.hub.api.deps import require_agent
from courtyard.hub.core.channels import ChannelService
from courtyard.hub.core.errors import NotAllowed
from courtyard.hub.core.registry import Registry

router = APIRouter(prefix="/agents", tags=["channels"])


def get_channels(request: Request) -> ChannelService:
    return request.app.state.channels


def _own(request: Request, name_or_id: str, caller: Agent) -> Agent:
    registry: Registry = request.app.state.registry
    agent = registry.get(name_or_id)
    if agent.id != caller.id:
        raise NotAllowed("token does not belong to this agent")
    return caller


class AttachRequest(BaseModel):
    endpoint: str  # the adapter's local receive URL
    channel_token: str  # adapter-generated; the hub presents it on every push
    # item 33 (D29): the adapter's report on the parent claude process's channels flag
    channel_flag: Literal["present", "absent", "unknown"] = "unknown"


class AckRequest(BaseModel):
    token: str  # the nonce from the delivery-check message (item 34, D30)


@router.post("/{name_or_id}/attach")
def attach(
    name_or_id: str,
    body: AttachRequest,
    request: Request,
    caller: Annotated[Agent, Depends(require_agent)],
    channels: Annotated[ChannelService, Depends(get_channels)],
) -> AttachSummary:
    agent = _own(request, name_or_id, caller)
    summary = channels.attach(agent, body.endpoint, body.channel_token, body.channel_flag)
    # Catch-up: push the queued backlog to the fresh channel, oldest first (design §6.4).
    channels.deliver_backlog(agent.id)
    return summary


@router.post("/{name_or_id}/heartbeat")
def heartbeat(
    name_or_id: str,
    request: Request,
    caller: Annotated[Agent, Depends(require_agent)],
    channels: Annotated[ChannelService, Depends(get_channels)],
) -> dict:
    agent = _own(request, name_or_id, caller)
    return channels.heartbeat(agent)


@router.post("/{name_or_id}/ack")
def ack_delivery(
    name_or_id: str,
    body: AckRequest,
    request: Request,
    caller: Annotated[Agent, Depends(require_agent)],
    channels: Annotated[ChannelService, Depends(get_channels)],
) -> dict:
    """Item 34 (D30): the model returns a delivery-check token. ok=False means the
    token matched no open check (timed out or superseded) — not an error."""
    agent = _own(request, name_or_id, caller)
    return {"ok": channels.ack_delivery(agent, body.token)}


@router.post("/{name_or_id}/verify-delivery")
def verify_delivery(
    name_or_id: str,
    request: Request,
    channels: Annotated[ChannelService, Depends(get_channels)],
) -> dict:
    """Item 34 (D30): operator surface (unauthenticated in v1, like the board) — the
    on-demand check behind the agent card's button."""
    registry: Registry = request.app.state.registry
    agent = registry.get(name_or_id)
    channels.begin_delivery_check(agent)
    return {"ok": True}


@router.post("/{name_or_id}/detach")
def detach(
    name_or_id: str,
    request: Request,
    caller: Annotated[Agent, Depends(require_agent)],
    channels: Annotated[ChannelService, Depends(get_channels)],
) -> dict:
    agent = _own(request, name_or_id, caller)
    channels.detach(agent)
    return {"ok": True}
