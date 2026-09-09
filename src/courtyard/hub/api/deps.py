"""FastAPI dependencies: app-state accessors and bearer-token agent auth."""

from __future__ import annotations

from typing import Annotated

from fastapi import Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from courtyard.common.models import Agent
from courtyard.hub.core.archive import Archiver
from courtyard.hub.core.board import Board
from courtyard.hub.core.errors import InvalidToken
from courtyard.hub.core.memory import Memory
from courtyard.hub.core.registry import Registry
from courtyard.hub.core.teams import TeamService


def get_registry(request: Request) -> Registry:
    return request.app.state.registry


def get_board(request: Request) -> Board:
    return request.app.state.board


def get_archiver(request: Request) -> Archiver:
    return request.app.state.archiver


def get_teams(request: Request) -> TeamService:
    return request.app.state.teams


def get_memory(request: Request) -> Memory:
    return request.app.state.memory


# Declared for the OpenAPI document only (Swagger's Authorize button); the header is read
# by hand below so a missing or malformed token stays a domain error (401 invalid_token).
_bearer = HTTPBearer(auto_error=False, description="the agent's token from its launch config")


def require_agent(
    request: Request,
    _creds: Annotated[HTTPAuthorizationCredentials | None, Security(_bearer)] = None,
) -> Agent:
    """Identify the caller by its bearer token (agent-scoped endpoints only)."""
    auth = request.headers.get("authorization", "")
    scheme, _, token = auth.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise InvalidToken("missing bearer token")
    registry: Registry = request.app.state.registry
    return registry.authenticate(token.strip())
