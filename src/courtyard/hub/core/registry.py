"""Agent registry: invite, resolve (hard-fail on unknown names), authenticate, remove."""

from __future__ import annotations

import hashlib
import logging
import secrets
from typing import Any
from uuid import UUID, uuid4

from courtyard.common.models import Agent
from courtyard.hub.core.errors import (
    CannotRemoveOperator,
    InvalidToken,
    NameTaken,
    UnknownAgent,
)
from courtyard.hub.storage.repo import Storage, UnitOfWork

logger = logging.getLogger("courtyard.hub")

OPERATOR_NAME = "operator"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Registry:
    def __init__(self, storage: Storage):
        self._storage = storage

    def create(
        self,
        name: str,
        type: str,
        description: str | None = None,
        workdir: str | None = None,
        launch: dict[str, Any] | None = None,
    ) -> tuple[Agent, str]:
        """Register an agent; the plaintext token is returned exactly once, here."""
        token = secrets.token_urlsafe(32)
        with self._storage.transaction() as uow:
            if uow.agents.get_by_name(name) is not None:
                raise NameTaken(f"agent name {name!r} is already registered")
            agent = uow.agents.create(
                agent_id=uuid4(),
                name=name,
                type=type,
                description=description,
                workdir=workdir,
                token_hash=hash_token(token),
                launch=launch,
            )
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
            return self.resolve(uow, name_or_id)

    def list(self) -> list[Agent]:
        with self._storage.transaction() as uow:
            return uow.agents.list()

    def authenticate(self, token: str) -> Agent:
        with self._storage.transaction() as uow:
            agent = uow.agents.get_by_token_hash(hash_token(token))
        if agent is None or agent.status == "gone":
            raise InvalidToken("unknown or revoked agent token")
        return agent

    def remove(self, name_or_id: str) -> Agent:
        """Mark an agent gone (history is retained, so rows are never deleted)."""
        with self._storage.transaction() as uow:
            agent = self.resolve(uow, name_or_id)
            if agent.name == OPERATOR_NAME:
                raise CannotRemoveOperator("the operator registration cannot be removed")
            uow.agents.set_status(agent.id, "gone")
            return uow.agents.get(agent.id)

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
            "created operator agent %s — token (shown once, only needed for the agent API): %s",
            agent.id,
            token,
        )
        return agent
