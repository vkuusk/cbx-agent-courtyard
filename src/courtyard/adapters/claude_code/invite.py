"""courtyard-invite — put a Claude Code agent's launch config into its project (step 6d).

A thin operator convenience over the hub's install API: it writes `<workdir>/.mcp.json`
(merging with anything already there, keeping a backup) so the agent starts with the
courtyard MCP server — the operator never hand-edits the file.

    # existing agent (paste the token shown once at registration):
    courtyard-invite --name coding --token cy_… --workdir ~/proj/payments

    # register and install in one step:
    courtyard-invite --register --name coding --type claude-code \\
        --sme-domain "the payments service" --workdir ~/proj/payments

    # undo it:
    courtyard-invite --name coding --workdir ~/proj/payments --remove

Dev-mode only: the hub writes the file, so it must share this machine's filesystem (the
normal local setup). In live/container mode use the WebUI's copy-paste config instead.
The written file carries the token and is chmod 600 — do not commit it.
"""

from __future__ import annotations

import argparse
import sys

from courtyard.common.client import DEFAULT_HUB_URL, HubClient, HubError


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="courtyard-invite", description=__doc__)
    p.add_argument("--hub", default=DEFAULT_HUB_URL, help=f"hub URL (default {DEFAULT_HUB_URL})")
    p.add_argument("--name", required=True, help="the agent's courtyard name")
    p.add_argument("--token", help="the agent's bearer token (from registration)")
    p.add_argument("--workdir", help="the agent's project dir (default: its registered workdir)")
    p.add_argument("--remove", action="store_true", help="undo a previous install")
    p.add_argument("--register", action="store_true", help="register the agent first, then install")
    p.add_argument(
        "--type", default="claude-code", help="agent type when --register (default claude-code)"
    )
    p.add_argument("--description", help="what the agent is for (when --register)")
    p.add_argument("--sme-domain", help="what the agent owns (when --register)")
    return p


def cli(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    client = HubClient(args.hub)
    try:
        if args.remove:
            result = client.uninstall(args.name, args.workdir)
            where = result["path"]
            how = (
                "restored the pre-install file"
                if result["restored_from_backup"]
                else "removed the courtyard entry"
            )
            print(f"courtyard-invite: {how} at {where}")
            return

        token = args.token
        if args.register:
            _agent, token = client.register_agent(
                args.name, args.type, args.description, args.sme_domain, args.workdir
            )
            print(f"registered {args.name}; token (shown once): {token}")
        if not token:
            _parser().error("provide --token, or use --register to create the agent")

        result = client.install(args.name, token, args.workdir)
        print(f"courtyard-invite: wrote {result['path']}")
        if result["backed_up"]:
            print(f"  (backed up the previous file to {result['backed_up']})")
        print(f"  {result['warning']}")
    except HubError as exc:
        print(f"courtyard-invite: hub refused: {exc}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    cli()
