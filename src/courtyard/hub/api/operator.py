"""Operator endpoints — the WebUI acting as the operator (design §5.6).

Unauthenticated like the rest of the admin surface (D3, localhost trust): the WebUI is
the operator's tunnel, so these resolve the operator agent server-side instead of
handing the operator token to the browser.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from courtyard.common.models import Agent, Message
from courtyard.hub.api.deps import get_board
from courtyard.hub.core.board import Board
from courtyard.hub.core.registry import OPERATOR_NAME

router = APIRouter(prefix="/operator", tags=["operator"])


def get_operator(request: Request) -> Agent:
    return request.app.state.registry.get(OPERATOR_NAME)


class OperatorSend(BaseModel):
    to: str  # recipient name or id
    body: str


@router.post("/send", status_code=201)
def send(
    body: OperatorSend,
    operator: Annotated[Agent, Depends(get_operator)],
    board: Annotated[Board, Depends(get_board)],
) -> Message:
    """Operator-initiated message: a normal line with normal turn rules, never gated."""
    return board.send(operator, body.to, body.body)


@router.get("/inbox")
def inbox(
    operator: Annotated[Agent, Depends(get_operator)],
    board: Annotated[Board, Depends(get_board)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[Message]:
    """Everything addressed to the operator, newest first (non-consuming history read)."""
    return board.inbox_history(operator, limit)
