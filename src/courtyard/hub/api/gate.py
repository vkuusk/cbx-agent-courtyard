"""Gate endpoints: the human approver's REST surface (design doc §5.5)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from courtyard.common.models import GateVerdict, Message
from courtyard.hub.api.deps import get_board
from courtyard.hub.core.board import Board

router = APIRouter(prefix="/gate", tags=["gate"])


class Decision(BaseModel):
    verdict: GateVerdict
    note: str | None = None


@router.get("/pending")
def pending(board: Annotated[Board, Depends(get_board)]) -> list[Message]:
    return board.pending()


@router.post("/{message_id}")
def decide(
    message_id: UUID, body: Decision, board: Annotated[Board, Depends(get_board)]
) -> Message:
    return board.decide(message_id, body.verdict, body.note)
