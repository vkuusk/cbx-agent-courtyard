"""Line endpoints: sending (agent-scoped), history, mode dial, notes, release."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from courtyard.common.models import Agent, Archive, Line, LineMode, Message
from courtyard.hub.api.deps import get_archiver, get_board, require_agent
from courtyard.hub.core.archive import Archiver
from courtyard.hub.core.board import Board

router = APIRouter(prefix="/lines", tags=["lines"])


class SendRequest(BaseModel):
    to: str  # recipient name or id; the sender is the token owner
    body: str


class ModeRequest(BaseModel):
    mode: LineMode


class NoteRequest(BaseModel):
    target: str = "both"  # participant name or id, or "both" (the default, design §5.6)
    body: str


@router.post("/send", status_code=201)
def send(
    body: SendRequest,
    sender: Annotated[Agent, Depends(require_agent)],
    board: Annotated[Board, Depends(get_board)],
) -> Message:
    return board.send(sender, body.to, body.body)


@router.get("")
def list_lines(board: Annotated[Board, Depends(get_board)]) -> list[Line]:
    return board.lines()


@router.get("/{line_id}")
def get_line(line_id: UUID, board: Annotated[Board, Depends(get_board)]) -> Line:
    return board.line(line_id)


@router.get("/{line_id}/messages")
def line_messages(
    line_id: UUID,
    board: Annotated[Board, Depends(get_board)],
    after: int | None = None,
) -> list[Message]:
    return board.line_messages(line_id, after)


@router.post("/{line_id}/mode")
def set_mode(line_id: UUID, body: ModeRequest, board: Annotated[Board, Depends(get_board)]) -> Line:
    return board.set_mode(line_id, body.mode)


@router.post("/{line_id}/note", status_code=201)
def add_note(
    line_id: UUID, body: NoteRequest, board: Annotated[Board, Depends(get_board)]
) -> list[Message]:
    return board.note(line_id, body.target, body.body)


@router.post("/{line_id}/release")
def release(line_id: UUID, board: Annotated[Board, Depends(get_board)]) -> Line:
    return board.release(line_id)


@router.post("/{line_id}/archive")
def archive(line_id: UUID, archiver: Annotated[Archiver, Depends(get_archiver)]) -> Archive:
    """Archive the history so far (design §5.7); the line continues, empty and idle."""
    return archiver.archive_line(line_id)
