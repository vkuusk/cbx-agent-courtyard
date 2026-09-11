"""Agent registry: invite, resolve (hard-fail on unknown names), authenticate, tokens, remove."""

from __future__ import annotations

import hashlib
import logging
import secrets
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from courtyard.common.models import AGENT_COLORS, Agent, PeersView
from courtyard.hub.core.archive import archive_line_in
from courtyard.hub.core.errors import (
    AgentGone,
    CannotRemoveOperator,
    InvalidToken,
    NameTaken,
    NoStoredToken,
    NotAllowed,
    UnknownAgent,
)
from courtyard.hub.core.events import EventBus
from courtyard.hub.core.peers import peers_view
from courtyard.hub.storage.repo import Storage, UnitOfWork

logger = logging.getLogger("courtyard.hub")

OPERATOR_NAME = "operator"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(32)


def pick_color(agents: list[Agent]) -> str:
    """The least-used palette colour among the current team (ties: palette order)."""
    used = Counter(
        a.color for a in agents if a.color and a.removed_at is None and a.type != "human"
    )
    return min(AGENT_COLORS, key=lambda c: (used.get(c, 0), AGENT_COLORS.index(c)))


class Registry:
    def __init__(
        self,
        storage: Storage,
        events: EventBus,
        discovery: Callable[[], str] | None = None,
    ):
        self._storage = storage
        self._events = events
        # §5.8 (D22): under manual discovery the peers list narrows to linked agents.
        self._discovery = discovery or (lambda: "auto")
        # agent id -> when an attach under its name last came with a token that is not its
        # own. In memory on purpose: the adapter retries every 2 s, so a hub restart refills
        # it within seconds, and an attach with the right token ends it.
        self._token_rejections: dict[UUID, datetime] = {}
        # every agent event, whoever publishes it (liveness, the shift, a heartbeat),
        # carries the note: the WebUI keeps the last event's object as the whole truth
        self._events.view("agent", self._with_rejection)

    def create(
        self,
        name: str,
        type: str,
        description: str | None = None,
        sme_domain: str | None = None,
        workdir: str | None = None,
        launch: dict[str, Any] | None = None,
        color: str | None = None,
        model: str | None = None,
        anti_scope: str | None = None,
    ) -> tuple[Agent, str]:
        """Register an agent. The token is returned here and kept (D19): the operator can
        read it again via `token_of` and replace it via `rotate_token`. Every agent but the
        operator gets a palette colour — the one given, or the least used.

        A name that was removed is registered again on its own row (his ask, 2026-09-08:
        a team member removed by mistake, or re-registered from a fresh charter, must get
        its name back). The old life is over — the token is replaced, liveness restarts at
        `invited`, the type may differ — and only the row survives it, which is exactly
        what keeps the archives and old messages that point at it valid. A live name is
        still refused."""
        token = new_token()
        with self._storage.transaction() as uow:
            existing = uow.agents.get_by_name(name)
            if existing is not None and existing.removed_at is None:
                raise NameTaken(f"agent name {name!r} is already registered")
            if color is None and type != "human":
                color = pick_color(uow.agents.list())
            fields = {
                "type": type,
                "description": description,
                "sme_domain": sme_domain,
                "workdir": workdir,
                "token_hash": hash_token(token),
                "token": token,
                "launch": launch,
                "color": color,
                "model": model,
                "anti_scope": anti_scope,
            }
            if existing is None:
                agent = uow.agents.create(agent_id=uuid4(), name=name, **fields)
            else:
                agent = uow.agents.revive(existing.id, **fields)
        self._events.publish("agent", agent)
        return agent, token

    def update(self, name_or_id: str, patch: dict[str, Any]) -> Agent:
        """Edit an agent's operator-owned fields (WP-D, item 8): description, sme_domain,
        anti_scope, workdir, model, color. Name and type are permanent identities — never
        editable. An explicit None clears a field; absent keys are untouched."""
        editable = {"description", "sme_domain", "anti_scope", "workdir", "model", "color"}
        unknown = set(patch) - editable
        if unknown:
            raise NotAllowed(f"not editable: {', '.join(sorted(unknown))}")
        with self._storage.transaction() as uow:
            agent = self.resolve(uow, name_or_id)
            if agent.type == "human":
                raise NotAllowed("the operator record is not editable")
            if agent.removed_at is not None:
                raise AgentGone(f"{agent.name} was removed from the courtyard")
            if patch:
                uow.agents.update(agent.id, patch)
            agent = uow.agents.get(agent.id)
        self._events.publish("agent", agent)
        return agent

    def token_of(self, name_or_id: str) -> str:
        """The agent's stored token, for the launch config (D19)."""
        with self._storage.transaction() as uow:
            agent = self.resolve(uow, name_or_id)
            if agent.removed_at is not None:
                raise AgentGone(
                    f"{agent.name} was removed from the courtyard; its token is revoked"
                )
            token = uow.agents.get_token(agent.id)
        if token is None:
            raise NoStoredToken(
                f"{agent.name} was registered before tokens were kept; rotate its token to get one"
            )
        return token

    def rotate_token(self, name_or_id: str) -> tuple[Agent, str]:
        """Replace the agent's token. Its running session can no longer reach the hub, so
        its channel is dropped and it reads as offline until restarted with the new token."""
        token = new_token()
        with self._storage.transaction() as uow:
            agent = self.resolve(uow, name_or_id)
            if agent.removed_at is not None:
                raise AgentGone(f"{agent.name} was removed from the courtyard; nothing to rotate")
            uow.agents.set_token(agent.id, hash_token(token), token)
            uow.channels.delete(agent.id)
            if agent.status != "invited":
                uow.agents.set_status(agent.id, "gone")
            agent = uow.agents.get(agent.id)
        self._events.publish("agent", agent)
        return agent, token

    def resolve(self, uow: UnitOfWork, name_or_id: str) -> Agent:
        """Name or UUID -> Agent; hard-fail rather than guess (design doc §5.1)."""
        agent = None
        try:
            agent = uow.agents.get(UUID(name_or_id))
        except ValueError:
            agent = uow.agents.get_by_name(name_or_id)
        if agent is None:
            raise UnknownAgent(f"no agent named {name_or_id!r}")
        return agent

    def get(self, name_or_id: str) -> Agent:
        with self._storage.transaction() as uow:
            return self._with_rejection(self.resolve(uow, name_or_id))

    def list(self) -> list[Agent]:
        with self._storage.transaction() as uow:
            return [self._with_rejection(a) for a in uow.agents.list()]

    # -- rejected tokens: "not started yet" would hide a file that can never work ---------

    def _with_rejection(self, agent: Agent) -> Agent:
        at = self._token_rejections.get(agent.id)
        return agent.model_copy(update={"token_rejected_at": at}) if at else agent

    def note_token_rejected(self, name_or_id: str) -> None:
        """An attach for a known agent name carried a token the hub does not know. Almost
        always a workdir's .mcp.json written before the database was rebuilt or the token
        rotated; retrying cannot fix it, so the card says so until the files are rewritten.
        Unknown names record nothing (nothing to show them on)."""
        try:
            with self._storage.transaction() as uow:
                agent = self.resolve(uow, name_or_id)
        except UnknownAgent:
            return
        if agent.removed_at is not None:
            return
        first = agent.id not in self._token_rejections
        self._token_rejections[agent.id] = datetime.now(UTC)
        if first:
            self._events.publish("agent", agent)

    def clear_token_rejected(self, agent: Agent) -> None:
        """An attach with the right token: the note is over (the attach's own agent event
        carries the cleared field to the WebUI)."""
        self._token_rejections.pop(agent.id, None)

    def peers(self, agent: Agent) -> PeersView:
        """Who this agent can talk to — ranked, trimmed and rendered hub-side (D14).
        Under manual discovery (§5.8) that is the agents it shares a line with, plus the
        operator, who never needs a link."""
        with self._storage.transaction() as uow:
            linked = None
            if self._discovery() == "manual":
                linked = {
                    line.agent_b if line.agent_a == agent.id else line.agent_a
                    for line in uow.lines.list_for_agent(agent.id)
                }
            return peers_view(uow.agents.list(), agent, linked)

    def authenticate(self, token: str) -> Agent:
        with self._storage.transaction() as uow:
            agent = uow.agents.get_by_token_hash(hash_token(token))
        if agent is None or agent.removed_at is not None:
            raise InvalidToken("unknown or revoked agent token")
        return agent

    def remove(self, name_or_id: str) -> Agent:
        """Mark an agent removed. Its lines can never be used again, so each one's history
        is archived (design §5.7, D20) and the line rows go; the registration stays
        (names are permanent identities)."""
        with self._storage.transaction() as uow:
            agent = self.resolve(uow, name_or_id)
            if agent.name == OPERATOR_NAME:
                raise CannotRemoveOperator("the operator registration cannot be removed")
            uow.agents.mark_removed(agent.id)
            uow.channels.delete(agent.id)
            archives = [
                archive_line_in(
                    uow, uow.lines.get_locked(line.id), "agent_removed", keep_line=False
                )[0]
                for line in uow.lines.list_for_agent(agent.id)
            ]
            agent = uow.agents.get(agent.id)
        self._events.publish("agent", agent)
        for archive in archives:
            self._events.publish("archive", archive)
        return agent

    def ensure_operator(self) -> Agent:
        """Create the operator agent on first run (design doc §5.1)."""
        with self._storage.transaction() as uow:
            existing = uow.agents.get_by_name(OPERATOR_NAME)
            if existing is not None:
                return existing
        agent, token = self.create(
            OPERATOR_NAME, "human", description="the human operator of this courtyard"
        )
        logger.info(
            "created operator agent %s — token (stored; only needed for the agent API): %s",
            agent.id,
            token,
        )
        return agent
