"""The team charter registry (design team-charter.md, D33). Admin surface,
unauthenticated like the rest (D3, localhost trust). Reloading or selecting the
current team also projects the charter into registrations and lines (slice 2), and
writes the files of every agent that registers, or whose workdir is answered, into its
workdir; `shift_active` refusals mean: end the shift first."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from courtyard.common.models import Team
from courtyard.hub.api.deps import get_teams
from courtyard.hub.core.teams import TeamService

router = APIRouter(prefix="/teams", tags=["teams"])


class TeamAdd(BaseModel):
    charter_dir: str
    # only needed to bootstrap an empty directory; the API answers
    # `charter_name_required` when it is missing and the directory is empty
    name: str | None = Field(default=None, max_length=120)


def hub_url(request: Request) -> str:
    """What the agents' files point at: the address the hub was reached on, as the
    install endpoint writes it."""
    return str(request.base_url).rstrip("/")


@router.get("")
def list_teams(teams: Annotated[TeamService, Depends(get_teams)]) -> list[Team]:
    return teams.list()


@router.post("", status_code=201)
def add_team(body: TeamAdd, teams: Annotated[TeamService, Depends(get_teams)]) -> Team:
    return teams.add(body.charter_dir, body.name)


@router.post("/{team_id}/reload")
def reload_team(
    team_id: UUID, request: Request, teams: Annotated[TeamService, Depends(get_teams)]
) -> Team:
    return teams.reload(team_id, hub_url(request))


class CurrentTeam(BaseModel):
    team_id: UUID | None = None  # null = no current team


@router.post("/current")
def set_current(
    body: CurrentTeam, request: Request, teams: Annotated[TeamService, Depends(get_teams)]
) -> list[Team]:
    return teams.set_current(body.team_id, hub_url(request))


class WorkdirSet(BaseModel):
    agent: str
    workdir: str


@router.post("/{team_id}/workdirs")
def set_workdir(
    team_id: UUID,
    body: WorkdirSet,
    request: Request,
    teams: Annotated[TeamService, Depends(get_teams)],
) -> Team:
    """Record one agent's per-machine project directory in the charter's overlay file
    (workdirs.local.yml), then reload — for the current team that carries the workdir
    into the registration and writes the agent's files into the directory."""
    return teams.set_workdir(team_id, body.agent, body.workdir, hub_url(request))


@router.delete("/{team_id}")
def remove_team(team_id: UUID, teams: Annotated[TeamService, Depends(get_teams)]) -> Team:
    """Drop the registry entry; the files stay the operator's."""
    return teams.remove(team_id)
