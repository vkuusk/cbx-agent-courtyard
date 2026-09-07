"""The team charter registry (design team-charter.md, D33). Admin surface,
unauthenticated like the rest (D3, localhost trust). Slice 1 is registration,
loading and selection only — projecting a charter into registrations comes later."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from courtyard.common.models import Team
from courtyard.hub.core.teams import TeamService

router = APIRouter(prefix="/teams", tags=["teams"])


def get_teams(request: Request) -> TeamService:
    return request.app.state.teams


class TeamAdd(BaseModel):
    charter_dir: str
    # only needed to bootstrap an empty directory; the API answers
    # `charter_name_required` when it is missing and the directory is empty
    name: str | None = Field(default=None, max_length=120)


@router.get("")
def list_teams(teams: Annotated[TeamService, Depends(get_teams)]) -> list[Team]:
    return teams.list()


@router.post("", status_code=201)
def add_team(body: TeamAdd, teams: Annotated[TeamService, Depends(get_teams)]) -> Team:
    return teams.add(body.charter_dir, body.name)


@router.post("/{team_id}/reload")
def reload_team(team_id: UUID, teams: Annotated[TeamService, Depends(get_teams)]) -> Team:
    return teams.reload(team_id)


class CurrentTeam(BaseModel):
    team_id: UUID | None = None  # null = no current team


@router.post("/current")
def set_current(body: CurrentTeam, teams: Annotated[TeamService, Depends(get_teams)]) -> list[Team]:
    return teams.set_current(body.team_id)


@router.delete("/{team_id}")
def remove_team(team_id: UUID, teams: Annotated[TeamService, Depends(get_teams)]) -> Team:
    """Drop the registry entry; the files stay the operator's."""
    return teams.remove(team_id)
