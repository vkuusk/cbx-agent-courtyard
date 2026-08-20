"""Channel registry and liveness (design §6.2–§6.4).

Identity is durable, sessions are not: attach registers (or replaces) the agent's one
receive endpoint, heartbeats keep it `connected`, missed beats decay it to `stale` then
`gone`. Liveness is advisory — it drives UI badges and push short-circuiting; line and
turn state are never touched by it.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse
from uuid import UUID, uuid4

from courtyard.common.models import Agent, AttachSummary, LineSummary, PeerInfo
from courtyard.hub.core.deliver import Deliverer
from courtyard.hub.core.errors import InvalidEndpoint, NotAttached
from courtyard.hub.core.events import EventBus
from courtyard.hub.core.registry import OPERATOR_NAME
from courtyard.hub.storage.repo import Storage, UnitOfWork

logger = logging.getLogger("courtyard.hub")

LOCAL_ENDPOINT_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _check_endpoint(endpoint: str) -> None:
    parsed = urlparse(endpoint)
    if parsed.scheme != "http" or parsed.hostname not in LOCAL_ENDPOINT_HOSTS:
        raise InvalidEndpoint(
            f"channel endpoint must be a local http:// URL, got {endpoint!r} "
            "(courtyard v1 is localhost-only)"
        )


class ChannelService:
    def __init__(
        self,
        storage: Storage,
        events: EventBus,
        deliverer: Deliverer,
        heartbeat_seconds: float,
        gone_seconds: float,
    ):
        self._storage = storage
        self._events = events
        self._deliverer = deliverer
        self._stale_after = 3 * heartbeat_seconds  # 3 missed beats (design §6.3)
        self._gone_after = gone_seconds

    # -- the adapter contract (attach / heartbeat / detach) --------------------------

    def attach(self, agent: Agent, endpoint: str, channel_token: str) -> AttachSummary:
        """Register the agent's receive endpoint; last attach wins. Returns the catch-up
        summary; the caller then pushes the queued backlog."""
        _check_endpoint(endpoint)
        with self._storage.transaction() as uow:
            previous = uow.channels.get(agent.id)
            uow.channels.upsert(agent.id, endpoint, channel_token)
            uow.agents.set_status(agent.id, "connected")
            uow.agents.touch(agent.id)
            updated = uow.agents.get(agent.id)
            warning = None
            if previous is not None and agent.status == "connected":
                warning = self._warn_replaced(uow, agent)
            summary = self._build_summary(uow, updated)
        self._events.publish("agent", updated)
        if warning is not None:
            self._events.publish("message", warning)
        return summary

    def deliver_backlog(self, agent_id: UUID) -> int:
        return self._deliverer.deliver_backlog(agent_id)

    def heartbeat(self, agent: Agent) -> dict:
        with self._storage.transaction() as uow:
            channel = uow.channels.heartbeat(agent.id)
            if channel is None:
                raise NotAttached(f"agent {agent.name!r} has no attached channel")
            uow.agents.touch(agent.id)
            revived = agent.status != "connected"
            if revived:
                uow.agents.set_status(agent.id, "connected")
                updated = uow.agents.get(agent.id)
            queued = uow.messages.count_queued_for(agent.id)
        if revived:
            self._events.publish("agent", updated)
        return {"ok": True, "status": "connected", "queued": queued}

    def detach(self, agent: Agent) -> None:
        with self._storage.transaction() as uow:
            if uow.channels.get(agent.id) is None:
                raise NotAttached(f"agent {agent.name!r} has no attached channel")
            uow.channels.delete(agent.id)
            uow.agents.set_status(agent.id, "gone")
            updated = uow.agents.get(agent.id)
        self._events.publish("agent", updated)

    # -- liveness sweep (advisory; run periodically by the hub) ----------------------

    def sweep(self) -> list[Agent]:
        """Decay connected -> stale -> gone by heartbeat age; returns agents that changed."""
        changed: list[Agent] = []
        with self._storage.transaction() as uow:
            for channel in uow.channels.list():
                agent = uow.agents.get(channel.agent_id)
                if agent.removed_at is not None:
                    continue
                age = channel.heartbeat_age_seconds or 0.0
                target = None
                if agent.status == "connected" and age > self._stale_after:
                    target = "stale"
                if agent.status in ("connected", "stale") and age > self._gone_after:
                    target = "gone"
                if target is not None:
                    uow.agents.set_status(agent.id, target)
                    changed.append(uow.agents.get(agent.id))
        for agent in changed:
            logger.info("liveness: %s -> %s", agent.name, agent.status)
            self._events.publish("agent", agent)
        return changed

    # -- internals -------------------------------------------------------------------

    def _warn_replaced(self, uow: UnitOfWork, agent: Agent):
        """The replaced channel was still live: two sessions may claim one identity.
        Logged as a system entry on the operator's line with this agent (design §6.4)."""
        operator = uow.agents.get_by_name(OPERATOR_NAME)
        line = uow.lines.get_or_create_locked(operator.id, agent.id)
        return uow.messages.insert(
            message_id=uuid4(),
            line_id=line.id,
            sender=None,
            recipient=None,  # log-only board entry
            kind="system",
            body=(
                f"agent {agent.name!r} attached a new channel while its previous one was "
                "still connected — two sessions may be claiming this identity"
            ),
            reply_to=None,
            status="delivered",
        )

    def _build_summary(self, uow: UnitOfWork, agent: Agent) -> AttachSummary:
        roster = [
            PeerInfo(name=a.name, type=a.type, description=a.description, status=a.status)
            for a in uow.agents.list()
            if a.removed_at is None and a.id != agent.id
        ]
        lines = []
        for line in uow.lines.list_for_agent(agent.id):
            peer_id = line.agent_b if line.agent_a == agent.id else line.agent_a
            peer = uow.agents.get(peer_id)
            your_turn = line.state == "awaiting_reply" and line.awaiting_from == agent.id
            in_flight = None
            if your_turn and line.in_flight_msg is not None:
                in_flight = uow.messages.get(line.in_flight_msg)
            lines.append(
                LineSummary(
                    line_id=line.id,
                    peer=peer.name,
                    mode=line.mode,
                    state=line.state,
                    your_turn=your_turn,
                    in_flight=in_flight,
                )
            )
        queued = uow.messages.count_queued_for(agent.id)
        return AttachSummary(agent=agent, roster=roster, lines=lines, queued=queued)
