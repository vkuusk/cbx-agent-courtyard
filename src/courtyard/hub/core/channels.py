"""Channel registry and liveness (design §6.2–§6.4).

Identity is durable, sessions are not: attach registers (or replaces) the agent's one
receive endpoint, heartbeats keep it `connected`, missed beats decay it to `stale` then
`gone`. Liveness is advisory — it drives UI badges and push short-circuiting; line and
turn state are never touched by it.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse
from uuid import UUID, uuid4

from courtyard.common.models import Agent, AttachSummary, LineSummary
from courtyard.hub.core.deliver import Deliverer
from courtyard.hub.core.errors import InvalidEndpoint, NotAttached
from courtyard.hub.core.events import EventBus
from courtyard.hub.core.peers import roster
from courtyard.hub.core.registry import OPERATOR_NAME
from courtyard.hub.storage.repo import Storage, UnitOfWork

logger = logging.getLogger("courtyard.hub")

LOCAL_ENDPOINT_HOSTS = {"127.0.0.1", "localhost", "::1"}

# D26: how much older than one heartbeat interval the hub must be before it judges an
# `unknown` agent — the same margin the shift's grace uses (design §6.3, §8.1).
JUDGE_MARGIN_SECONDS = 5.0


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
        hub_started_at: datetime | None = None,
        discovery: Callable[[], str] | None = None,
    ):
        self._storage = storage
        self._events = events
        self._deliverer = deliverer
        # §5.8 (D22): under manual discovery the attach-summary roster narrows to linked agents.
        self._discovery = discovery or (lambda: "auto")
        self._stale_after = 3 * heartbeat_seconds  # 3 missed beats (design §6.3)
        self._gone_after = gone_seconds
        # D26: `unknown` agents are judged only after this — one heartbeat interval plus
        # margin from hub start, so a live adapter always gets its beat in first.
        self._judge_after = (hub_started_at or datetime.now(UTC)) + timedelta(
            seconds=heartbeat_seconds + JUDGE_MARGIN_SECONDS
        )

    @property
    def judging(self) -> bool:
        """True while the hub is too young to judge `unknown` agents (D26). The sweeper
        runs on a fast cadence while this holds (+ one pass after), so resolution lands
        within a second of the boundary — one transition, not a straggling second one."""
        return datetime.now(UTC) < self._judge_after + timedelta(seconds=1)

    def reset_unverified(self) -> int:
        """D26, called once at hub startup: stored `connected`/`stale` are claims from a
        previous hub life — flip them to `unknown` rather than repeat them unverified.
        The first heartbeat proves an agent live again at any moment; the sweep resolves
        the rest once the hub is past its judging grace."""
        with self._storage.transaction() as uow:
            unverified = [
                agent
                for agent in uow.agents.list()
                if agent.status in ("connected", "stale") and agent.removed_at is None
            ]
            for agent in unverified:
                uow.agents.set_status(agent.id, "unknown")
            changed = [uow.agents.get(agent.id) for agent in unverified]
        for agent in changed:
            self._events.publish("agent", agent)
        if changed:
            logger.info(
                "liveness: %s unverified after restart -> unknown (judging after %s)",
                ", ".join(agent.name for agent in changed),
                self._judge_after.isoformat(timespec="seconds"),
            )
        return len(changed)

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
            rearmed = self._rearm_undischarged(uow, updated)
            summary = self._build_summary(uow, updated)
        self._events.publish("agent", updated)
        if warning is not None:
            self._events.publish("message", warning)
        for message in rearmed:
            self._events.publish("message", message)
        for line_id in {m.line_id for m in rearmed}:
            with self._storage.transaction() as uow:
                line = uow.lines.get(line_id)
            self._events.publish("line", line)  # its queued counter changed
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
        """Decay connected -> stale -> gone by heartbeat age; returns agents that changed.

        `unknown` agents (D26, set at hub startup) are left alone while the hub is
        younger than one heartbeat window — a live adapter's beat flips them straight to
        connected — and resolved to their true state afterwards, all in one pass."""
        changed: list[Agent] = []
        judging = datetime.now(UTC) < self._judge_after
        with self._storage.transaction() as uow:
            channels = {channel.agent_id: channel for channel in uow.channels.list()}
            for agent in uow.agents.list():
                if agent.removed_at is not None:
                    continue
                channel = channels.get(agent.id)
                age = (channel.heartbeat_age_seconds or 0.0) if channel else None
                target = None
                if agent.status == "unknown":
                    if judging:
                        continue
                    if age is None or age > self._gone_after:
                        target = "gone"
                    else:
                        target = "stale"  # a later heartbeat still revives it
                elif channel is not None:
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

    def _rearm_undischarged(self, uow: UnitOfWork, agent: Agent) -> list:
        """R1 (design §6.4, D24): a message delivered to a *previous* session and never
        answered is an obligation nobody alive can fulfil — flip it back to `queued` so
        the backlog push after this attach delivers it into the new session. A `system`
        entry marks the second delivery in history. Messages `expired` at end of shift
        are excluded by their status: that close was intentional."""
        rearmed = uow.messages.rearm_undischarged(agent.id)
        published = []
        for message in rearmed:
            uow.lines.get_locked(message.line_id)  # insert bumps the per-line seq
            entry = uow.messages.insert(
                message_id=uuid4(),
                line_id=message.line_id,
                sender=None,
                recipient=None,  # log-only board entry
                kind="system",
                body=(
                    f"the message (seq {message.seq}) was delivered to a previous "
                    f"session of {agent.name} and never answered — redelivered"
                ),
                reply_to=message.id,
                status="delivered",
            )
            logger.info("rearm: seq %s on line %s -> %s", message.seq, message.line_id, agent.name)
            published.extend([message, entry])
        return published

    def _build_summary(self, uow: UnitOfWork, agent: Agent) -> AttachSummary:
        my_lines = uow.lines.list_for_agent(agent.id)
        linked = None
        if self._discovery() == "manual":  # §5.8: the roster follows the lines
            linked = {
                line.agent_b if line.agent_a == agent.id else line.agent_a for line in my_lines
            }
        peers = roster(uow.agents.list(), agent, linked)  # reachable first, like `GET /peers`
        lines = []
        for line in my_lines:
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
        return AttachSummary(agent=agent, roster=peers, lines=lines, queued=queued)
