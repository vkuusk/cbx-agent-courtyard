"""The team registry (design team-charter.md, D33): registered charter directories, one
of them current. Slice 1 was the read path (register, load, display, reload, select);
slice 2 adds projection: whenever the CURRENT team's charter is (re)loaded, its cards
become registrations and its links become lines, so the database stays the projection of
the files. Loads happen only on explicit operator gestures (add, reload, select, a
workdir answer, a write-back); the hub never watches the filesystem.

Projection is additive and idempotent: it creates what is missing and mirrors the
charter-owned fields onto what exists; it never removes an agent or a line. Removal is
the write-back direction (slice 3): while a team is current, agent add/edit/remove
through the hub also writes the charter files, so an agent leaves the team by leaving
the files — whether the operator edited them by hand or the hub did it for them.
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

from courtyard.common.models import Agent, Charter, CharterCard, Team
from courtyard.hub.core import charter
from courtyard.hub.core.board import Board
from courtyard.hub.core.errors import (
    AlreadyLinked,
    CharterNameRequired,
    CharterNotLoaded,
    CharterWriteFailed,
    DomainError,
    NoTeam,
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
        """Select the current team. Becoming current is the initialization gesture: it
        adopts any agent no registered team's charter names, then reloads and projects
        the charter. The courtyard always has a current team once one was chosen
        (D33, revised): the selection cannot be cleared, only moved."""
        if team_id is None:
            if self.current() is not None:
                raise NoTeam(
                    "the courtyard always has a current team; select another team "
                    "instead of clearing the selection"
                )
            return self.list()  # nothing was current; nothing to clear
        if self._shift_active():
            raise ShiftActive("a shift is running; end it before changing the current team")
        with self._storage.transaction() as uow:
            if not uow.teams.get(team_id):
                raise TeamNotFound("no such team")
            uow.teams.set_current(team_id)
        self._adopt_orphans()
        self.reload(team_id)
        return self.list()

    def _adopt_orphans(self) -> None:
        """D33 (revised): choosing a team on a hub that already holds agents adopts the
        ones no registered team's charter names — they are written into the now-current
        team's charter as cards, explicitly, at this gesture. A charter that did not
        load adopts nothing (the load report already says why)."""
        team = self.current()
        if team is None or team.charter is None:
            return
        claimed = {card.name for t in self.list() if t.charter for card in t.charter.agents}
        with self._storage.transaction() as uow:
            agents = uow.agents.list()
        for agent in agents:
            if agent.type == "human" or agent.removed_at is not None or agent.name in claimed:
                continue
            self.writeback_created(agent)

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
        so does everything an earlier projection created — removal is not teardown.
        The current team cannot be removed (D33, revised): select another first."""
        with self._storage.transaction() as uow:
            team = uow.teams.get(team_id)
            if not team:
                raise TeamNotFound("no such team")
            if team.is_current:
                raise NoTeam(
                    "this team is current and the courtyard always has one; "
                    "select another team before removing it"
                )
            uow.teams.delete(team_id)
            return team

    # -- write-back from the agent forms (design team-charter.md §3, slice 3) ---------
    # The registration endpoints call these around the registry's own operations: an
    # agent added, edited or removed through the hub is also written into (or out of)
    # the current team's charter files, so the files stay the master and the next
    # reload finds nothing to disagree with. No current team = refused (`no_team`).
    # No shift guard here: single-agent edits were always allowed mid-shift, and the
    # database change already happened through the registry, events and all.

    def check_writeback(self) -> None:
        """Called before a registration change so a doomed write-back refuses BEFORE
        the database is touched; without this the agent would land in the database
        with no charter entry, a divergence the additive reload never heals. No
        current team refuses too (D33, revised): the charter is the source of truth,
        so it needs a home before the first agent."""
        if self.current() is None:
            raise NoTeam(
                "no team is current; choose the team's charter directory first "
                "(Admin -> Teams: an empty directory is initialized for you)"
            )
        self._writeback_team()

    def writeback_created(self, agent: Agent, declared_color: str | None = None) -> None:
        """A new registration joins the current team's charter: yml entry, config dir,
        card files, and its workdir into the per-machine overlay. The colour goes into
        card.yml only when the request declared one; a hub-picked colour stays the
        hub's, exactly as projection treats an undeclared colour."""
        team = self._writeback_team()
        if team is None or agent.type == "human":
            return
        charter_dir = Path(team.charter_dir)
        try:
            rel = charter.add_agent_entry(charter_dir, agent.name)
            charter.write_card(
                charter_dir,
                rel,
                {
                    "type": agent.type,
                    "model": agent.model,
                    "color": declared_color,
                    "description": agent.description,
                    "sme_domain": agent.sme_domain,
                    "anti_scope": agent.anti_scope,
                },
            )
            if agent.workdir:
                charter.set_workdir(charter_dir, agent.name, agent.workdir)
        except (OSError, ValueError) as exc:
            raise CharterWriteFailed(
                f"{agent.name} is registered on the hub, but writing it into the team "
                f"charter failed: {exc}. Fix the charter directory and either remove "
                "the agent or add it to the files by hand, then reload."
            ) from exc
        self._refresh(team)

    def writeback_updated(self, agent: Agent, patch: dict) -> None:
        """An edit of a charter agent lands on its card files; a patched workdir lands
        on the overlay. An agent outside the current charter (it belongs to another
        registered team) is edited in the database only: its master is elsewhere."""
        team = self._writeback_team()
        if team is None:
            return
        card = next((c for c in team.charter.agents if c.name == agent.name), None)
        if card is None:
            return
        charter_dir = Path(team.charter_dir)
        try:
            fields = {k: v for k, v in patch.items() if k != "workdir"}
            if fields:
                charter.write_card(charter_dir, card.config_dir, fields)
            if "workdir" in patch:
                charter.set_workdir(charter_dir, agent.name, patch["workdir"])
        except (OSError, ValueError) as exc:
            raise CharterWriteFailed(
                f"{agent.name} is updated on the hub, but writing the team charter "
                f"failed: {exc}. Fix the charter directory, mirror the edit into the "
                "files by hand if needed, then reload."
            ) from exc
        self._refresh(team)

    def writeback_removed(self, name: str) -> None:
        """A removed charter agent leaves the files too — its yml entry, links, overlay
        workdir and configuration directory — else the next reload would report the
        permanent name as unregisterable forever."""
        team = self._writeback_team()
        if team is None or all(c.name != name for c in team.charter.agents):
            return
        try:
            charter.remove_agent_entry(Path(team.charter_dir), name)
        except (OSError, ValueError) as exc:
            raise CharterWriteFailed(
                f"{name} is removed from the hub, but taking it out of the team charter "
                f"failed: {exc}. Remove it from the files by hand, or every reload will "
                "report the name (removed names are permanent)."
            ) from exc
        self._refresh(team)

    def _writeback_team(self) -> Team | None:
        """The team agent changes write back to: the current one, charter loaded. None
        only in the transient pre-team state (check_writeback refuses registration
        there first). A current team whose charter did not load refuses instead: the
        hub cannot write into files it could not read, and it cannot even tell which
        agents the charter holds."""
        team = self.current()
        if team is None:
            return None
        if team.charter is None:
            raise CharterNotLoaded(
                "the current team's charter did not load; fix the files and reload the "
                "team, or clear the team selection, before changing agents"
            )
        return team

    def _refresh(self, team: Team) -> None:
        """Re-read the charter right after a write-back so the cached copy matches the
        files the hub just wrote. No projection: the database change already went
        through the registry, this only keeps the Teams view honest."""
        loaded, report = charter.load_charter(Path(team.charter_dir))
        with self._storage.transaction() as uow:
            uow.teams.set_loaded(
                team.id,
                loaded.name if loaded else team.name,
                loaded.model_dump() if loaded else None,
                report,
            )

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
        # a removed name is registered again (the registry revives its row): the files
        # are the master, and a charter that names it wants it on the team
        if existing is None or existing.removed_at is not None:
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
