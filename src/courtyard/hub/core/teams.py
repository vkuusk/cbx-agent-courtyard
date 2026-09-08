"""The team registry (design team-charter.md, D33): registered charter directories, one
of them current. Slice 1 was the read path (register, load, display, reload, select);
slice 2 adds projection: whenever the CURRENT team's charter is (re)loaded, its cards
become registrations and its links become lines, so the database stays the projection of
the files. Loads happen only on explicit operator gestures (add, reload, select, a
workdir answer); the hub never watches the filesystem.

Projection is additive and idempotent: it creates what is missing and mirrors the
charter-owned fields onto what exists; it never removes an agent or a line (removal is
the write-back direction, slice 3 — an agent leaves the team by leaving the files).
Problems land in the team's load report next to the loader's own, because the WebUI's
job is to display what happened, not to abort on it.

Like Settings, team changes publish no SSE event of their own: the Admin tab that made
the change updates from the response, other tabs catch up on their next snapshot — and
the agents and lines projection creates announce themselves through the registry's and
board's normal events.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from uuid import UUID, uuid4

from courtyard.common.models import Charter, CharterCard, Team
from courtyard.hub.core import charter
from courtyard.hub.core.board import Board
from courtyard.hub.core.errors import (
    AlreadyLinked,
    CharterNameRequired,
    DomainError,
    ShiftActive,
    TeamExists,
    TeamNotFound,
    UnknownAgent,
    WorkdirNotFound,
)
from courtyard.hub.core.registry import Registry
from courtyard.hub.storage.repo import Storage


class TeamService:
    def __init__(
        self,
        storage: Storage,
        registry: Registry | None = None,
        board: Board | None = None,
        shift_active: Callable[[], bool] | None = None,
        set_discovery: Callable[[str], None] | None = None,
    ):
        self._storage = storage
        self._registry = registry
        self._board = board
        # D33 guard: projection changes registrations under live agents, so reloading or
        # selecting the current team is refused while a shift runs (end it first).
        self._shift_active = shift_active or (lambda: False)
        # a charter may declare the team's discovery regime; the callable writes it into
        # the hub settings (the shift service owns the settings document)
        self._set_discovery = set_discovery or (lambda _v: None)

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
        (item 43 follow-up: the offer replaced a flat refusal for non-empty dirs).
        Adding never projects: a team changes the courtyard only once it is current."""
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
        are ready (a git pull landed, an edit finished, a workdir was answered). For
        the current team this is also the moment the database is made to match."""
        with self._storage.transaction() as uow:
            team = uow.teams.get(team_id)
        if not team:
            raise TeamNotFound("no such team")
        if team.is_current and self._shift_active():
            raise ShiftActive("a shift is running; end it before reloading the current team")
        loaded, report = charter.load_charter(Path(team.charter_dir))
        if team.is_current and loaded:
            report = report + self._project(loaded)
        with self._storage.transaction() as uow:
            updated = uow.teams.set_loaded(
                team_id,
                loaded.name if loaded else team.name,
                loaded.model_dump() if loaded else None,
                report,
            )
        if not updated:
            raise TeamNotFound("no such team")
        return updated

    def set_current(self, team_id: UUID | None) -> list[Team]:
        """Select the current team. Becoming current is the initialization gesture, so
        it reloads and projects the charter right away; clearing the selection changes
        no registrations and needs no guard."""
        if team_id is not None and self._shift_active():
            raise ShiftActive("a shift is running; end it before changing the current team")
        with self._storage.transaction() as uow:
            if team_id is not None and not uow.teams.get(team_id):
                raise TeamNotFound("no such team")
            uow.teams.set_current(team_id)
        if team_id is not None:
            self.reload(team_id)
        return self.list()

    def set_workdir(self, team_id: UUID, agent_name: str, workdir: str) -> Team:
        """Answer the per-machine workdir question for one charter agent (ask-at-init,
        D33): record it in the overlay file, then reload so the registration follows."""
        with self._storage.transaction() as uow:
            team = uow.teams.get(team_id)
        if not team:
            raise TeamNotFound("no such team")
        if not team.charter or agent_name not in {a.name for a in team.charter.agents}:
            raise UnknownAgent(f"no agent named {agent_name!r} in this charter")
        path = Path(workdir).expanduser().resolve()
        if not path.is_dir():
            raise WorkdirNotFound(f"{path} is not a directory the hub can see")
        charter.set_workdir(Path(team.charter_dir), agent_name, str(path))
        return self.reload(team_id)

    def remove(self, team_id: UUID) -> Team:
        """Drop the registry entry; the charter files are the operator's and stay, and
        so does everything an earlier projection created — removal is not teardown."""
        with self._storage.transaction() as uow:
            team = uow.teams.get(team_id)
            if not team:
                raise TeamNotFound("no such team")
            uow.teams.delete(team_id)
            return team

    # -- projection (design team-charter.md §6) ---------------------------------------

    def _project(self, loaded: Charter) -> list[str]:
        """Make the database match the charter: cards become registrations, links become
        lines, a declared discovery regime becomes the Settings dial. Additive only;
        returns the problems found, load-report style."""
        problems: list[str] = []
        if loaded.discovery:
            # reasserted on every reload, like declared line modes: the files are the
            # master for what they state. Undeclared = the dial stays the operator's.
            self._set_discovery(loaded.discovery)
        names = (self._project_card(card, problems) for card in loaded.agents)
        placed = {name for name in names if name}
        lines = {frozenset((li.agent_a_name, li.agent_b_name)): li for li in self._board.lines()}
        for link in loaded.links:
            if not {link.a, link.b} <= placed:
                continue  # the failed card is already reported; half a link helps nobody
            existing = lines.get(frozenset((link.a, link.b)))
            if existing is None:
                try:
                    self._board.link(link.a, link.b, mode=link.mode)
                except AlreadyLinked:
                    pass  # raced into existence; the mode reassert below is lost until reload
                except DomainError as exc:
                    problems.append(f"link {link.a} - {link.b}: {exc}")
            elif link.mode and existing.mode != link.mode:
                # files are the master: a declared mode is reasserted on every reload
                self._board.set_mode(existing.id, link.mode)
        return problems

    def _project_card(self, card: CharterCard, problems: list[str]) -> str | None:
        """One card into one registration; returns the name when it is in place."""
        with self._storage.transaction() as uow:
            existing = uow.agents.get_by_name(card.name)
        if existing is None:
            if card.type is None:
                problems.append(f"agent {card.name}: card.yml declares no type; not registered")
                return None
            self._registry.create(
                card.name,
                card.type,
                description=card.description,
                sme_domain=card.sme_domain,
                workdir=card.workdir,
                color=card.color,
                model=card.model,
                anti_scope=card.anti_scope,
            )
            return card.name
        if existing.type == "human":
            problems.append(
                f"agent {card.name}: that is the operator, on the roster by design (D9), "
                "never a charter agent"
            )
            return None
        if existing.removed_at is not None:
            problems.append(
                f"agent {card.name}: this name was removed from the courtyard and names are "
                "permanent; pick a new one in the charter"
            )
            return None
        if card.type and card.type != existing.type:
            problems.append(
                f"agent {card.name}: registered as {existing.type} but the charter says "
                f"{card.type}; the type is a permanent identity and stays {existing.type}"
            )
        # The files are the master for what they own: prose and model mirror the charter
        # exactly (a file removed clears the field). The workdir is per-machine and only
        # ever set from the overlay; the colour is a hub-assigned nicety unless declared.
        fields: dict = {
            "description": card.description,
            "sme_domain": card.sme_domain,
            "anti_scope": card.anti_scope,
            "model": card.model,
        }
        if card.color:
            fields["color"] = card.color
        if card.workdir:
            fields["workdir"] = card.workdir
        self._registry.update(card.name, fields)
        return card.name
