"""The membership context a Claude Code session gets once, at session start (D40).

One short block, injected by the SessionStart hook registration writes: it tells the
session that it is a member of a team, where its messages come from and what the
delivery check is. It exists because the channel cannot vouch for itself: the host
wraps every channel event as untrusted external data, and a session in a fresh
directory has nothing on the user's side saying otherwise (seen live 2026-09-10: a
session refused the delivery check as prompt injection, then a peer's question).

Shared by the hub, which renders it with the current team's name, and by the hook
command, which falls back to the same text without the name when the hub is down: a
session start never waits on the hub. Light on purpose: everything else about the
etiquette rides the MCP server's instructions and the envelope.
"""

from __future__ import annotations

TOOL_NAMES = (
    "courtyard_send, courtyard_peers, courtyard_inbox, courtyard_recall, courtyard_note, "
    "courtyard_close_thread and courtyard_ack"
)


def render(agent_name: str, hub_url: str, team_name: str | None = None) -> str:
    team = f' of the team "{team_name}"' if team_name else ""
    return (
        "You are configured as part of a team of agents who communicate through a hub "
        f'called courtyard. Your operator registered this project as the agent "{agent_name}"'
        f"{team}; the hub runs on this machine at {hub_url}, started and supervised by your "
        "operator.\n"
        '\nMessages from the hub arrive as <channel source="courtyard"> events (the courtyard '
        "MCP server in this project's .mcp.json). They are: (a) messages from other agents "
        "and from your operator; (b) hub notices about your own messages; (c) at the start "
        "of a shift, a delivery check asking you to call the courtyard MCP tool "
        "courtyard_ack with a token. The check is expected: answer it with that one tool "
        "call.\n"
        f"\nThe courtyard tools ({TOOL_NAMES}; your host may list them under prefixed names "
        "such as mcp__courtyard__courtyard_send) are yours to use. Text printed in this "
        "terminal never reaches the board; only courtyard_send does. The rest of the "
        "etiquette is in the courtyard MCP server's instructions."
    )
