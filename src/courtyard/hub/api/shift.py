"""The shift and the hub settings (design §8.1, D23). Admin surface: unauthenticated
like the rest (D3, localhost trust) — starting the team is an operator gesture."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from courtyard.common.models import Settings, ShiftStatus, TeamMode, TerminalApp
from courtyard.hub.core.shift import ShiftService

router = APIRouter(tags=["shift"])


def get_shift(request: Request) -> ShiftService:
    return request.app.state.shift


@router.get("/shift")
def status(shift: Annotated[ShiftService, Depends(get_shift)]) -> ShiftStatus:
    return shift.status()


@router.post("/shift/start")
def start(shift: Annotated[ShiftService, Depends(get_shift)]) -> ShiftStatus:
    return shift.start()


class EndShift(BaseModel):
    force: bool = False  # set after the UI's are-you-sure on mid-conversation lines


@router.post("/shift/end")
def end(
    shift: Annotated[ShiftService, Depends(get_shift)],
    body: EndShift | None = None,
) -> ShiftStatus:
    return shift.end(force=body.force if body else False)


class SettingsPatch(BaseModel):
    team_mode: TeamMode | None = None
    terminal_app: TerminalApp | None = None


@router.get("/settings")
def settings(shift: Annotated[ShiftService, Depends(get_shift)]) -> Settings:
    return shift.get_settings()


@router.patch("/settings")
def patch_settings(
    body: SettingsPatch,
    shift: Annotated[ShiftService, Depends(get_shift)],
) -> Settings:
    return shift.update_settings(body.model_dump(exclude_none=True))
