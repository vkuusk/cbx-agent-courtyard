"""The membership context a session gets at its start (D40): Claude Code from the
SessionStart hook registration writes, pi from the courtyard extension.

One short block: it tells the session that it is a member of a team, which agent it is
(whatever its directory is called), where its messages come from and what the delivery
check is. It exists because the channel cannot vouch for itself: Claude Code wraps every
channel event as untrusted external data, and a session in a fresh directory has nothing
on the user's side saying otherwise (seen live 2026-09-10: a session refused the
delivery check as prompt injection, then a peer's question). pi showed the other side of
the same gap (2026-09-11): the session acked the check, then spent 33 seconds working out
which agent it was, because pi loads the etiquette skill only on demand.

Shared by the hub, which renders it with the current team's name and worded for the
agent's type, and by the fallbacks (the hook command, and the text install renders into
the pi extension), which carry the same text without the name: a session start never
waits on the hub. Light on purpose: everything else about the etiquette rides the MCP
server's instructions (Claude Code), the courtyard skill (pi) and the envelope.
"""

from __future__ import annotations

TOOL_NAMES = (
    "courtyard_send, courtyard_peers, courtyard_inbox, courtyard_recall, courtyard_note, "
    "courtyard_close_thread and courtyard_ack"
)


def render(
    agent_name: str, hub_url: str, team_name: str | None = None, agent_type: str = "claude-code"
) -> str:
    team = f' of the team "{team_name}"' if team_name else ""
    pi = agent_type == "pi"
    arrival = (
        "Messages from the hub arrive as courtyard messages that the courtyard extension in "
        "this project (.pi/extensions/courtyard.ts) adds to this session"
        if pi
        else 'Messages from the hub arrive as <channel source="courtyard"> events (the '
        "courtyard MCP server in this project's .mcp.json)"
    )
    ack_tool = "the tool courtyard_ack" if pi else "the courtyard MCP tool courtyard_ack"
    tools = (
        f"The courtyard tools ({TOOL_NAMES}) are yours to use."
        if pi
        else f"The courtyard tools ({TOOL_NAMES}; your host may list them under prefixed "
        "names such as mcp__courtyard__courtyard_send) are yours to use."
    )
    etiquette = (
        "the courtyard skill in this project (.pi/skills/courtyard/SKILL.md)"
        if pi
        else "the courtyard MCP server's instructions"
    )
    return (
        "You are configured as part of a team of agents who communicate through a hub "
        f'called courtyard. Your operator registered this project as the agent "{agent_name}"'
        f"{team}; that is your name on the board, whatever this project's directory is "
        f"called. The hub runs on this machine at {hub_url}, started and supervised by your "
        "operator.\n"
        f"\n{arrival}. They are: (a) messages from other agents and from your operator; "
        "(b) hub notices about your own messages; (c) at the start of a shift, a delivery "
        f"check asking you to call {ack_tool} with a token. The check is expected: answer "
        "it with that one tool call. When a courtyard message asks nothing more of you, end "
        "your turn and wait: do not look for work, inspect the project or message anyone "
        "unless your operator or a peer asks you to.\n"
        f"\n{tools} Text printed in this terminal never reaches the board; only "
        f"courtyard_send does. The rest of the etiquette is in {etiquette}."
    )
