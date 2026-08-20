"""Shared domain models — used by the hub now, by the client library from step 2 on."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel

AgentType = Literal["claude-code", "pi", "puppet", "human"]
AgentStatus = Literal["invited", "connected", "stale", "gone"]
LineMode = Literal["supervised", "auto_pass"]
LineState = Literal["idle", "pending_gate", "awaiting_reply"]
MessageKind = Literal["message", "operator_note", "system"]
MessageStatus = Literal["pending_gate", "queued", "delivered", "rejected", "returned"]
GateVerdict = Literal["approve", "return", "reject"]


class Agent(BaseModel):
    id: UUID
    name: str
    type: AgentType
    description: str | None = None  # operator-curated: what this agent is for
    workdir: str | None = None
    status: AgentStatus  # liveness only; removal is removed_at
    launch: dict[str, Any] | None = None
    created_at: datetime
    last_seen_at: datetime | None = None
    removed_at: datetime | None = None


class Line(BaseModel):
    id: UUID
    agent_a: UUID
    agent_b: UUID
    mode: LineMode
    state: LineState
    awaiting_from: UUID | None = None
    in_flight_msg: UUID | None = None
    created_at: datetime
    # display enrichment, filled by the storage layer's joins/aggregates (None on
    # locked reads inside transactions, which only the turn machine consumes)
    agent_a_name: str | None = None
    agent_b_name: str | None = None
    pending_count: int | None = None  # messages held at the gate
    queued_count: int | None = None  # accepted, not yet delivered
    last_activity_at: datetime | None = None


class Message(BaseModel):
    id: UUID
    line_id: UUID
    seq: int
    sender: UUID | None  # null = hub-generated (kind: system)
    recipient: UUID | None  # message: the other party; operator_note: its target; null = log-only
    kind: MessageKind
    body: str
    reply_to: UUID | None = None
    status: MessageStatus
    gate_verdict: GateVerdict | None = None
    gate_note: str | None = None
    gate_decided_by: UUID | None = None
    gate_decided_at: datetime | None = None
    created_at: datetime
    delivered_at: datetime | None = None
    # display enrichment, filled by the storage layer's joins
    sender_name: str | None = None
    recipient_name: str | None = None


class Channel(BaseModel):
    """An agent's live receive endpoint — exactly one per agent, last attach wins."""

    agent_id: UUID
    endpoint: str
    channel_token: str
    registered_at: datetime
    last_heartbeat: datetime
    # measured by the database clock at read time (liveness sweep input)
    heartbeat_age_seconds: float | None = None


class PeerInfo(BaseModel):
    """Roster entry in the attach summary — the discovery substrate (use-cases doc, entry 2)."""

    name: str
    type: AgentType
    description: str | None = None
    status: AgentStatus


class LineSummary(BaseModel):
    line_id: UUID
    peer: str
    mode: LineMode
    state: LineState
    your_turn: bool
    # the unanswered message awaiting your reply, if any (never a gated message)
    in_flight: Message | None = None


class AttachSummary(BaseModel):
    """Attach response: everything a (re)connecting agent needs to catch up (design §6.4)."""

    agent: Agent
    roster: list[PeerInfo]
    lines: list[LineSummary]
    queued: int  # backlog size; the hub pushes these right after this response is built
