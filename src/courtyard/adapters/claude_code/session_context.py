"""`courtyard-claude-context`: the SessionStart hook command (D40).

Claude Code runs it whenever a session (re)starts its context (startup, resume, clear,
compact, fork), from the hook entry registration wrote into `.claude/settings.local.json`;
it prints the hook's JSON with the membership context as `additionalContext`. The text
comes from the hub when the hub answers (it knows the current team's name), else from
the same template without it: a session start never waits on the hub, and the command
never fails.

    courtyard-claude-context --hub http://127.0.0.1:2626 --name tf-dev-agent
"""

from __future__ import annotations

import argparse
import json
import sys

import httpx

from courtyard.common import session_context

HUB_TIMEOUT = 2.0


def fetch(hub_url: str, agent_name: str) -> str:
    resp = httpx.get(f"{hub_url}/api/agents/{agent_name}/session-context", timeout=HUB_TIMEOUT)
    resp.raise_for_status()
    return str(resp.json()["text"])


def context(hub_url: str, agent_name: str) -> str:
    try:
        return fetch(hub_url, agent_name)
    except Exception:  # noqa: BLE001 - the hub being down is the case this covers
        return session_context.render(agent_name, hub_url)


def hook_output(text: str) -> str:
    return json.dumps(
        {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}}
    )


def cli(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="the courtyard SessionStart hook (D40)")
    parser.add_argument("--hub", required=True)
    parser.add_argument("--name", required=True)
    args = parser.parse_args(argv)
    sys.stdout.write(hook_output(context(args.hub, args.name)) + "\n")


if __name__ == "__main__":
    cli()
