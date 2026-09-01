"""deliver() — the one convergent delivery function (design §6.1).

Called after the transaction that persisted the message has committed. No routing, no
retry queues: push once; on failure the message stays `queued` and the pull path /
re-attach backlog picks it up. The network call happens outside any DB transaction.
"""

from __future__ import annotations

import logging

import httpx

from courtyard.common.models import Message
from courtyard.hub.core.envelope import with_rendering
from courtyard.hub.core.events import EventBus
from courtyard.hub.storage.repo import Storage

logger = logging.getLogger("courtyard.hub")

CHANNEL_TOKEN_HEADER = "X-Courtyard-Channel-Token"


class Deliverer:
    def __init__(self, storage: Storage, events: EventBus, push_timeout: float = 3.0):
        self._storage = storage
        self._events = events
        self._http = httpx.Client(timeout=push_timeout)

    def close(self) -> None:
        self._http.close()

    def deliver(self, message: Message) -> Message:
        """Attempt delivery of a committed `queued` message; return its final state."""
        if message.status != "queued" or message.recipient is None:
            return message

        with self._storage.transaction() as uow:
            recipient = uow.agents.get(message.recipient)
            channel = uow.channels.get(message.recipient)

        # A human's tunnel is the WebUI: visible as soon as it renders, so it is delivered.
        if recipient.type == "human":
            return self._mark_delivered(message)

        # Push short-circuit: no channel, or a channel we know is dead. Stays queued.
        if channel is None or recipient.status == "gone" or recipient.removed_at is not None:
            return message

        # The push carries the authority-graded envelope (§7.5), rendered here so
        # every adapter presents the same text (D14).
        pushed = self.push_raw(channel, with_rendering(message))

        if pushed:
            return self._mark_delivered(message)

        if recipient.status == "connected":
            with self._storage.transaction() as uow:
                uow.agents.set_status(recipient.id, "stale")
                stale = uow.agents.get(recipient.id)
            self._events.publish("agent", stale)
        return message

    def push_raw(self, channel, message: Message) -> bool:
        """One HTTP push of an already-rendered message to a channel endpoint. Also
        carries synthetic, storage-less messages — the delivery check (item 34) rides
        the same payload shape, so every adapter version forwards it unchanged."""
        try:
            resp = self._http.post(
                channel.endpoint,
                json={"message": message.model_dump(mode="json")},
                headers={CHANNEL_TOKEN_HEADER: channel.channel_token},
            )
            return resp.is_success
        except httpx.HTTPError as exc:
            logger.info("push to %s failed: %s", channel.endpoint, exc)
            return False

    def deliver_backlog(self, agent_id) -> int:
        """Push the agent's queued backlog in order (re-attach catch-up, design §6.4).

        Stops at the first failed push — order is preserved and the rest stays queued.
        Returns the number delivered.
        """
        with self._storage.transaction() as uow:
            backlog = uow.messages.list_queued_for(agent_id)
        delivered = 0
        for message in backlog:
            if self.deliver(message).status != "delivered":
                break
            delivered += 1
        return delivered

    def _mark_delivered(self, message: Message) -> Message:
        with self._storage.transaction() as uow:
            updated = uow.messages.mark_delivered(message.id)
            if updated is None:  # the pull path beat us to it
                updated = uow.messages.get(message.id)
            line = uow.lines.get(updated.line_id)
        self._events.publish("message", updated)
        self._events.publish("line", line)  # its queued counter changed
        return updated
