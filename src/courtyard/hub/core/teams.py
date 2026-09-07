"""The team registry (design team-charter.md, D33): registered charter directories, one
of them current. Slice 1 is the read path — register, load, display, reload, select;
nothing here touches agents, lines or the shift. Loads happen only on explicit operator
gestures (add, reload); the hub never watches the filesystem.

Like Settings, team changes publish no SSE event: the Admin tab that made the change
updates from the response, and other tabs catch up on their next snapshot.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

from courtyard.common.models import Team
from courtyard.hub.core import charter
from courtyard.hub.core.errors import (
    CharterNameRequired,
    TeamExists,
    TeamNotFound,
    WorkdirNotFound,
)
from courtyard.hub.storage.repo import Storage


class TeamService:
    def __init__(self, storage: Storage):
        self._storage = storage

    def list(self) -> list[Team]:
        with self._storage.transaction() as uow:
            return uow.teams.list()

    def current(self) -> Team | None:
        for team in self.list():
            if team.is_current:
                return team
        return None

    def add(self, charter_dir: str, name: str | None = None) -> Team:
        """Register a directory. One with a charter is loaded as found (problems land in
        the load report, not in an error). One without a charter can be initialized: the
        `charter_name_required` answer is the WebUI's cue to offer that, and the supplied
        name is the operator's confirmation — only then does the hub write the index
        (item 43 follow-up: the offer replaced a flat refusal for non-empty dirs)."""
        path = Path(charter_dir).expanduser().resolve()
        if not path.is_dir():
            raise WorkdirNotFound(f"{path} is not a directory the hub can see")
        if not (path / charter.CHARTER_FILE).is_file():
            if not name or not name.strip():
                raise CharterNameRequired(
                    f"{path} has no {charter.CHARTER_FILE}; give a team name to initialize it"
                )
            charter.create_charter(path, name.strip())
        loaded, report = charter.load_charter(path)
        with self._storage.transaction() as uow:
            if uow.teams.get_by_dir(str(path)):
                raise TeamExists(f"{path} is already registered")
            return uow.teams.insert(
                team_id=uuid4(),
                charter_dir=str(path),
                name=loaded.name if loaded else None,
                loaded=loaded.model_dump() if loaded else None,
                load_report=report,
            )

    def reload(self, team_id: UUID) -> Team:
        """Re-read the charter from disk — the operator's declaration that the files
        are ready (a git pull landed, an edit finished)."""
        with self._storage.transaction() as uow:
            team = uow.teams.get(team_id)
            if not team:
                raise TeamNotFound("no such team")
            loaded, report = charter.load_charter(Path(team.charter_dir))
            return uow.teams.set_loaded(
                team_id,
                loaded.name if loaded else team.name,
                loaded.model_dump() if loaded else None,
                report,
            )

    def set_current(self, team_id: UUID | None) -> list[Team]:
        with self._storage.transaction() as uow:
            if team_id is not None and not uow.teams.get(team_id):
                raise TeamNotFound("no such team")
            uow.teams.set_current(team_id)
            return uow.teams.list()

    def remove(self, team_id: UUID) -> Team:
        """Drop the registry entry; the charter files are the operator's and stay."""
        with self._storage.transaction() as uow:
            team = uow.teams.get(team_id)
            if not team:
                raise TeamNotFound("no such team")
            uow.teams.delete(team_id)
            return team
