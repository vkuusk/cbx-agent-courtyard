"""Shared domain models — used by the hub now, by the client library from step 2 on."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel

AgentType = Literal["claude-code", "pi", "puppet", "human"]
# `unknown` (D26): the hub restarted and has not yet verified this agent's stored
# liveness — resolved by the first heartbeat or by the sweep once the hub is old enough.
AgentStatus = Literal["invited", "connected", "stale", "gone", "unknown"]
LineMode = Literal["supervised", "auto_pass"]
LineState = Literal["idle", "pending_gate", "awaiting_reply"]
MessageKind = Literal["message", "operator_note", "system"]
MessageStatus = Literal["pending_gate", "queued", "delivered", "dropped", "returned", "expired"]
# `drop` (item 24, 2026-08-28; renames the original `reject` — too close to "return to
# sender"): the message is dropped at the gate, and the operator's comment travels nowhere.
GateVerdict = Literal["approve", "return", "drop"]
ArchiveReason = Literal["agent_removed", "operator", "unlinked"]
# Discovery (design §5.8, D22): who forms the team's wiring — `auto` lets a line form on
# the first message between any pair; `manual` means agents reach only whom the operator
# has linked (a link IS a pre-created idle line; its existence is the permission).
Discovery = Literal["auto", "manual"]

# The WebUI identity palette: a name, not a hex value — the UI renders a theme-appropriate tint.
AGENT_COLORS = ("red", "orange", "yellow", "green", "teal", "blue", "purple", "pink")
AgentColor = Literal["red", "orange", "yellow", "green", "teal", "blue", "purple", "pink"]


class Agent(BaseModel):
    id: UUID
    name: str
    type: AgentType
    description: str | None = None  # operator-curated: what this agent is for
    sme_domain: str | None = None  # operator-curated: what this agent OWNS (§7.5 grading)
    workdir: str | None = None
    model: str | None = None  # operator-declared model for the agent's runtime (WP-A);
    # install writes it into the agent's settings so nobody forgets to set it
    color: AgentColor | None = None  # WebUI identity colour; None only for the operator
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
    # authority grading inputs (design §7.5): the sender's role decides the grade, and
    # the two declared domains let the recipient weigh whose ground the message touches
    sender_type: AgentType | None = None
    sender_sme_domain: str | None = None
    recipient_sme_domain: str | None = None
    # filled by the hub on every agent-facing delivery (channel push, inbox pull): the
    # authority-graded envelope (design §7.5), ready for the model verbatim. Absent on
    # operator-facing reads (board, line history), which show the raw body.
    rendered: str | None = None


class Archive(BaseModel):
    """One archived line history (design §5.7): the line's identity at the time, why and
    when, and — on single reads and exports — the transcript as the board showed it."""

    id: UUID
    line_id: UUID  # the line it came from; gone if the archive came from a removal
    agent_a: UUID
    agent_b: UUID
    agent_a_name: str
    agent_b_name: str
    mode: LineMode
    reason: ArchiveReason
    archived_at: datetime
    first_at: datetime | None = None
    last_at: datetime | None = None
    message_count: int
    transcript: list[Message] | None = None  # omitted in listings and events


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
    sme_domain: str | None = None
    status: AgentStatus


class PeersView(BaseModel):
    """`GET /agents/{me}/peers`: who an agent can talk to, reachable first and trimmed, with
    the model-facing rendering done hub-side so adapters only forward it (D14)."""

    peers: list[PeerInfo]
    total: int  # live registrations before trimming
    rendered: str


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


TeamMode = Literal["on_shift", "always_on"]  # design §8.1 (D23); v1 implements on_shift
ShiftPhase = Literal["off", "starting", "on"]


class ShiftSpawn(BaseModel):
    """One terminal the shift opened — recorded so End shift closes exactly these."""

    agent_id: UUID
    agent_name: str
    window_ref: str | None = None  # spawner-specific handle; None if capture failed
    spawned_at: datetime


class ShiftStatus(BaseModel):
    """The whole shift picture (design §8.1): the WebUI pill renders from this, the
    countdown ticking locally from grace_until — the hub never streams a clock."""

    mode: TeamMode
    state: ShiftPhase
    started_at: datetime | None = None
    grace_until: datetime | None = None  # while starting: judge liveness only after this
    spawns: list[ShiftSpawn] = []
    skipped: list[str] = []  # agents the shift cannot launch (puppet, no workdir), by name
    # D25: the shift reads on, the hub is past its liveness grace, and not one target
    # agent is connected — the working period factually ended (terminals closed by hand,
    # a reboot) without the End gesture. The UI asks what to do; the hub never decides.
    stale: bool = False
    # D26: the hub restarted into a running shift and is still inside its liveness grace
    # — statuses are being verified. The UI shows "Checking the team" until this passes.
    checking_until: datetime | None = None


BUILTIN_TERMINALS = ("Terminal", "iTerm2")  # macOS apps the shift fully drives (open AND close)


class CustomTerminal(BaseModel):
    """An operator-defined terminal application (item 20): `command` is the start
    string, a shell template where `{dir}` and `{command}` are substituted quoted.
    It opens windows only — End shift cannot close what an arbitrary launcher opened."""

    name: str
    command: str


class Settings(BaseModel):
    """Hub-level settings the operator can change (Admin page)."""

    team_mode: TeamMode = "on_shift"
    # a BUILTIN_TERMINALS name, or the name of a custom_terminals entry; the shift
    # service validates membership on every change
    terminal_app: str = "Terminal"
    custom_terminals: list[CustomTerminal] = []
    # 7c: the supervision dial a NEW line starts on (D6 kept supervised as the default;
    # this is its promised relief valve). Existing lines keep whatever they were set to.
    default_line_mode: LineMode = "supervised"
    # §5.8 (D22): switching modes migrates nothing — under manual the lines that exist
    # ARE the links; operator lines are exempt and keep forming on first send.
    discovery: Discovery = "auto"
