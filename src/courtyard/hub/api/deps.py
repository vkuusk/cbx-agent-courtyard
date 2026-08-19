"""FastAPI dependencies: app-state accessors and bearer-token agent auth."""

from __future__ import annotations

from fastapi import Request

from courtyard.common.models import Agent
from courtyard.hub.core.board import Board
from courtyard.hub.core.errors import InvalidToken
from courtyard.hub.core.registry import Registry


def get_registry(request: Request) -> Registry:
    return request.app.state.registry


def get_board(request: Request) -> Board:
    return request.app.state.board


def require_agent(request: Request) -> Agent:
    """Identify the caller by its bearer token (agent-scoped endpoints only)."""
    auth = request.headers.get("authorization", "")
    scheme, _, token = auth.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise InvalidToken("missing bearer token")
    registry: Registry = request.app.state.registry
    return registry.authenticate(token.strip())
