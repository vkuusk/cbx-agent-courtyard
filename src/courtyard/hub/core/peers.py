"""Peer discovery, hub-side (design §7.1, D14): who an agent can talk to, ranked and rendered.

The peers list is read by a model deciding whom to ask, so it is ordered by reachability
and trimmed — a long tail of long-dead registrations is noise the model pays context for.
Ranking, trimming and the model-facing wording live here, once; adapters forward the text.
"""

from __future__ import annotations

from courtyard.common.models import Agent, PeerInfo, PeersView

PEER_LIMIT = 25  # a real courtyard holds a handful of agents; this only trims dev clutter
LIVENESS_ORDER = {"connected": 0, "stale": 1, "invited": 2, "gone": 3}


def roster(agents: list[Agent], me: Agent) -> list[PeerInfo]:
    """Every other live registration, reachable first, then by name."""
    others = [a for a in agents if a.removed_at is None and a.id != me.id]
    others.sort(key=lambda a: (LIVENESS_ORDER.get(a.status, 9), a.name))
    return [
        PeerInfo(
            name=a.name,
            type=a.type,
            description=a.description,
            sme_domain=a.sme_domain,
            status=a.status,
        )
        for a in others
    ]


def peers_view(agents: list[Agent], me: Agent) -> PeersView:
    everyone = roster(agents, me)
    shown = everyone[:PEER_LIMIT]
    hidden = len(everyone) - len(shown)
    return PeersView(peers=shown, total=len(everyone), rendered=render(shown, hidden))


def render(peers: list[PeerInfo], hidden: int) -> str:
    if not peers:
        return "You are the only agent on this courtyard board."
    lines = [
        f"{p.name} — {p.type}, {p.status}"
        + (f" — owns: {p.sme_domain}" if p.sme_domain else "")
        + (f" — {p.description}" if p.description else "")
        for p in peers
    ]
    if hidden:
        lines.append(f"(and {hidden} more registrations that have not been active)")
    return "Agents on the courtyard board (send with courtyard_send):\n" + "\n".join(lines)
