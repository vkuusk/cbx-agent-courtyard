"""Hub memory (design hub-memory.md, slice 1): the case file and recall.

The hub remembers collaboration, not craft. When a thread closes, the hub assembles
its story — the participants as they were, the opening ask, the resolution, every
verdict with its comment, the ordered messages — into one case file. The write-time
work is assembly, not summarization: no model call; the reader summarizes at read time.

Recall is the pull path back into an agent's context: a bounded number of trimmed
records matching a question, ranked with the participants' declared domains (the ask
and the domains weigh most, migration 0020), filtered by what the asking agent may see.
The hub renders the model-facing text (D14), so both adapters forward it as-is.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from uuid import UUID, uuid4

from courtyard.common.models import (
    Agent,
    Line,
    MemoryRecord,
    RecallView,
    Settings,
    Thread,
)
from courtyard.hub.core.errors import MemoryNotFound, NotAllowed
from courtyard.hub.core.registry import Registry
from courtyard.hub.storage.repo import Storage, UnitOfWork

RECALL_MAX = 20  # the hard ceiling on one recall, whatever the setting says


def case_file_in(uow: UnitOfWork, thread: Thread, line: Line, closed_by: Agent) -> MemoryRecord:
    """Inside the caller's transaction, right after the thread was ended `closed`: build the
    case file from the thread's messages and the line's two participants."""
    messages = uow.messages.list_thread(thread.id)
    participants = []
    for agent_id in (line.agent_a, line.agent_b):
        agent = uow.agents.get(agent_id)
        participants.append(
            {"id": str(agent.id), "name": agent.name, "sme_domain": agent.sme_domain}
        )
    spoken = [m for m in messages if m.kind == "message"]
    # the resolution is the last message that actually got through, not a dropped or
    # returned draft; with nothing through, the last thing said stands in
    landed = [m for m in spoken if m.status in ("delivered", "queued")]
    ask = spoken[0].body if spoken else ""
    resolution = (landed or spoken)[-1].body if spoken else ""
    verdicts = [
        f"{m.gate_verdict}: {m.gate_note.strip()}"
        for m in messages
        if m.gate_verdict and m.gate_note and m.gate_note.strip()
    ]
    counts = {"approve": 0, "return": 0, "drop": 0}
    for m in messages:
        if m.gate_verdict in counts:
            counts[m.gate_verdict] += 1
    return uow.memory.insert(
        record_id=uuid4(),
        kind="case",
        thread_id=thread.id,
        line_id=line.id,
        participants=participants,
        opened_by=thread.opened_by,
        opened_by_name=thread.opened_by_name,
        opened_at=thread.opened_at,
        closed_at=thread.ended_at,
        message_count=len(spoken),
        approved=counts["approve"],
        returned=counts["return"],
        dropped=counts["drop"],
        ask=ask,
        resolution=resolution,
        verdicts=verdicts,
        document={
            "messages": [m.model_dump(mode="json") for m in messages],
            "closed_by": closed_by.name,
        },
    )


def _cut(text: str, limit: int) -> tuple[str, bool]:
    text = text.strip()
    if len(text) <= limit:
        return text, False
    return text[: max(limit - 1, 1)].rstrip() + "…", True


def trim(record: MemoryRecord, chars: int) -> MemoryRecord:
    """The trimmed view: the ask and the resolution cut to the recall length."""
    ask, cut_a = _cut(record.ask, chars)
    resolution, cut_r = _cut(record.resolution, chars)
    return record.model_copy(
        update={"ask": ask, "resolution": resolution, "trimmed": cut_a or cut_r, "document": None}
    )


def _who(record: MemoryRecord) -> str:
    return " ↔ ".join(p.name for p in record.participants)


def _when(record: MemoryRecord) -> str:
    stamp = record.closed_at or record.created_at
    return stamp.strftime("%Y-%m-%d")


def render_listing(question: str, records: list[MemoryRecord]) -> str:
    """The recall tool's text: bounded, trimmed, each record with its handle."""
    if not records:
        return (
            f"The team's memory holds nothing matching {question!r}. Nobody has settled this "
            "through the courtyard before; ask the peer who owns it."
        )
    how = "best match first" if question.strip() else "newest first"
    lines = [
        (
            f"{len(records)} case file{'s' if len(records) != 1 else ''} from the team's "
            f"memory ({how}). Each is one closed exchange: who asked, what was settled, and "
            "the operator's verdicts. Fetch one in full with courtyard_recall(case=<id>)."
        ),
        "",
    ]
    for n, r in enumerate(records, 1):
        counts = []
        if r.returned:
            counts.append(f"{r.returned} returned")
        if r.dropped:
            counts.append(f"{r.dropped} dropped")
        tail = f", {', '.join(counts)}" if counts else ""
        lines.append(
            f"{n}. [{r.id}] {_who(r)}, closed {_when(r)}, "
            f"{r.message_count} message{'s' if r.message_count != 1 else ''}{tail}"
        )
        lines.append(f"   ask ({r.opened_by_name or '?'}): {r.ask or '(none)'}")
        lines.append(f"   resolution: {r.resolution or '(none)'}")
        for v in r.verdicts:
            lines.append(f"   verdict {v}")
        lines.append("")
    return "\n".join(lines).rstrip()


def render_case(record: MemoryRecord) -> str:
    """The full case file as text: header, then every message in order."""
    doc = record.document or {}
    lines = [
        (
            f"Case file [{record.id}]: {_who(record)}, opened by "
            f"{record.opened_by_name or '?'} {_when(record)}, closed by "
            f"{doc.get('closed_by') or '?'}; {record.message_count} "
            f"message{'s' if record.message_count != 1 else ''}, {record.approved} approved, "
            f"{record.returned} returned, {record.dropped} dropped."
        ),
        "",
    ]
    for m in doc.get("messages", []):
        who = m.get("sender_name") or ("hub" if m.get("kind") == "system" else "operator")
        to = m.get("recipient_name")
        verdict = ""
        if m.get("gate_verdict"):
            verdict = f" [{m['gate_verdict']}"
            if m.get("gate_note"):
                verdict += f": {m['gate_note']}"
            verdict += "]"
        head = f"{m.get('seq', '?')}. {who}" + (f" → {to}" if to else "") + verdict
        lines.append(head)
        lines.append("   " + (m.get("body") or "").replace("\n", "\n   "))
    return "\n".join(lines).rstrip()


class Memory:
    def __init__(
        self,
        storage: Storage,
        registry: Registry,
        settings: Callable[[], Settings],
        discovery: Callable[[], str] | None = None,
    ):
        self._storage = storage
        self._registry = registry
        self._settings = settings
        self._discovery = discovery or (lambda: "auto")

    # -- visibility (hub-memory.md section 8) -------------------------------------------

    def _visible_to(self, agent: Agent | None) -> UUID | None:
        """The participant filter an agent's reads carry: under `manual` discovery an
        agent recalls only from the lines it is party to, which is exactly the case
        files it appears in. The operator, and `auto`, see everything."""
        if agent is None or agent.type == "human" or self._discovery() != "manual":
            return None
        return agent.id

    # -- reads ---------------------------------------------------------------------------

    def search(
        self,
        *,
        question: str | None = None,
        participant: str | None = None,
        line_id: UUID | None = None,
        since: datetime | None = None,
        limit: int | None = None,
        as_agent: Agent | None = None,
    ) -> list[MemoryRecord]:
        settings = self._settings()
        limit = min(limit or settings.recall_limit, RECALL_MAX)
        with self._storage.transaction() as uow:
            who = self._registry.resolve(uow, participant).id if participant else None
            forced = self._visible_to(as_agent)
            if forced is not None and who is not None and who != forced:
                return []  # asking about someone else's lines: nothing to see
            records = uow.memory.search(
                question=question,
                participant=forced or who,
                line_id=line_id,
                since=since,
                limit=limit,
            )
        return [trim(r, settings.recall_trim_chars) for r in records]

    def get(self, record_id: UUID, as_agent: Agent | None = None) -> MemoryRecord:
        with self._storage.transaction() as uow:
            record = uow.memory.get(record_id)
        if record is None:
            raise MemoryNotFound("no such memory record")
        forced = self._visible_to(as_agent)
        if forced is not None and all(p.id != forced for p in record.participants):
            raise NotAllowed("this case file is from a line you are not party to")
        return record

    def recall(self, agent: Agent, question: str, limit: int | None = None) -> RecallView:
        """The agent-facing read (the `courtyard_recall` tool): trimmed, bounded,
        filtered, and rendered hub-side."""
        records = self.search(question=question, limit=limit, as_agent=agent)
        return RecallView(records=records, rendered=render_listing(question, records))

    def recall_case(self, agent: Agent, record_id: UUID) -> MemoryRecord:
        record = self.get(record_id, as_agent=agent)
        return record.model_copy(update={"rendered": render_case(record)})

    def count(self) -> int:
        with self._storage.transaction() as uow:
            return uow.memory.count()
