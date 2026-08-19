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
    status: AgentStatus
    launch: dict[str, Any] | None = None
    created_at: datetime
    last_seen_at: datetime | None = None


class Line(BaseModel):
    id: UUID
    agent_a: UUID
    agent_b: UUID
    mode: LineMode
    state: LineState
    awaiting_from: UUID | None = None
    in_flight_msg: UUID | None = None
    created_at: datetime


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
