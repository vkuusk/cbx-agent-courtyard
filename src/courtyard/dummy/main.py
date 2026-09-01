"""courtyard-dummy CLI.

    courtyard-dummy --name fake-infra --token TOKEN --behavior echo
    courtyard-dummy --name alice --token TOKEN --behavior script:alice.yaml \
        --open "bob: can you deploy the payments service?"
    courtyard-dummy --name me --token TOKEN --behavior manual

Manual mode is a tiny terminal client: type `peer: message` to send (bare text replies to
whoever wrote last). Until the WebUI exists (step 3) it doubles as the operator console:
/pending, /approve, /return, /drop, /auto, /release, /peers, /quit.
"""

from __future__ import annotations

import argparse
import os
import signal
import sys

import httpx

from courtyard.common.client import DEFAULT_HUB_URL, HubError
from courtyard.common.models import AttachSummary
from courtyard.dummy.core import (
    Behavior,
    Dummy,
    EchoBehavior,
    ManualBehavior,
    ScriptBehavior,
)

HELP = """commands:
  peer: message         send a message to `peer` (bare text: reply to the last sender)
  /peers                who is on the board
  /pending              messages waiting at the gate (numbered)
  /approve N [note]     gate verdicts on entry N of the last /pending list
  /return N [comment]
  /drop N [note]
  /auto PEER            flip your line with PEER to auto_pass  (/supervise to flip back)
  /supervise PEER
  /release PEER         release a stuck line with PEER to idle
  /quit                 detach and exit"""


def build_behavior(spec: str) -> Behavior:
    if spec == "echo":
        return EchoBehavior()
    if spec == "manual":
        return ManualBehavior()
    if spec.startswith("script:"):
        return ScriptBehavior.from_yaml(spec.removeprefix("script:"))
    raise SystemExit(f"unknown behavior {spec!r} (echo | script:<file.yaml> | manual)")


def print_summary(summary: AttachSummary) -> None:
    peers = summary.roster
    print(f"attached as {summary.agent.name!r} — {len(peers)} peer(s) on the board:")
    for p in peers:
        desc = f" — {p.description}" if p.description else ""
        print(f"  {p.name}  ({p.type}, {p.status}){desc}")
    for li in summary.lines:
        turn = "YOUR TURN" if li.your_turn else li.state
        print(f"  line with {li.peer}: mode={li.mode}, {turn}")
        if li.in_flight is not None:
            print(f"    awaiting your reply to seq {li.in_flight.seq}: {li.in_flight.body[:100]}")
    if summary.queued:
        print(f"  {summary.queued} queued message(s) incoming…")


class OperatorConsole:
    """The /-commands of manual mode (v1 pre-UI operator surface)."""

    def __init__(self, dummy: Dummy):
        self._dummy = dummy
        self._client = dummy.client
        self._pending: list = []

    def handle(self, line: str) -> bool:
        """Returns False when the REPL should exit."""
        cmd, _, rest = line.partition(" ")
        rest = rest.strip()
        try:
            self._dispatch(cmd, rest)
        except HubError as exc:
            print(f"  hub: {exc}")
        except (ValueError, IndexError):
            print(f"  bad arguments for {cmd}; see /help")
        return cmd != "/quit"

    def _dispatch(self, cmd: str, rest: str) -> None:
        if cmd == "/help":
            print(HELP)
        elif cmd == "/peers":
            for a in self._client.agents():
                if a.removed_at is None and a.name != self._dummy.name:
                    desc = f" — {a.description}" if a.description else ""
                    print(f"  {a.name}  ({a.type}, {a.status}){desc}")
        elif cmd == "/pending":
            self._pending = self._client.pending()
            if not self._pending:
                print("  gate is empty")
            for i, m in enumerate(self._pending, 1):
                print(f"  {i}. {m.sender_name} → {m.recipient_name} (seq {m.seq}): {m.body[:100]}")
        elif cmd in ("/approve", "/return", "/drop"):
            n, _, note = rest.partition(" ")
            message = self._pending[int(n) - 1]
            updated = self._client.decide(message.id, cmd.removeprefix("/"), note.strip() or None)
            print(f"  {updated.status}: {updated.sender_name} → {updated.recipient_name}")
        elif cmd in ("/auto", "/supervise", "/release"):
            line = self._line_with(rest)
            if cmd == "/release":
                self._client.release(line.id)
                print(f"  line with {rest} released to idle")
            else:
                mode = "auto_pass" if cmd == "/auto" else "supervised"
                self._client.set_mode(line.id, mode)
                print(f"  line with {rest} is now {mode}")
        elif cmd == "/quit":
            pass
        else:
            print(f"  unknown command {cmd}; see /help")

    def _line_with(self, peer_name: str):
        agents = {a.id: a.name for a in self._client.agents()}
        me = self._dummy.summary.agent.id
        for line in self._client.lines():
            pair = {line.agent_a, line.agent_b}
            if me in pair and peer_name in {agents.get(a) for a in pair - {me}}:
                return line
        raise HubError(404, "line_not_found", f"you have no line with {peer_name!r} yet")


def manual_repl(dummy: Dummy, behavior: ManualBehavior) -> None:
    console = OperatorConsole(dummy)
    print("type `peer: message` to talk, /help for commands")
    while True:
        try:
            raw = input()
        except (EOFError, KeyboardInterrupt):
            return
        line = raw.strip()
        if not line:
            continue
        if line.startswith("/"):
            if not console.handle(line):
                return
            continue
        peer, _, body = line.partition(":")
        if body.strip() and " " not in peer.strip():
            dummy.say(peer.strip(), body.strip())
        elif behavior.last_sender:
            dummy.say(behavior.last_sender, line)
        else:
            print("  no one to reply to yet — address someone: `peer: message`")


def cli() -> None:
    parser = argparse.ArgumentParser(prog="courtyard-dummy", description=__doc__)
    parser.add_argument("--hub", default=os.environ.get("COURTYARD_HUB_URL", DEFAULT_HUB_URL))
    parser.add_argument("--name", default=os.environ.get("COURTYARD_AGENT_NAME"), required=False)
    parser.add_argument("--token", default=os.environ.get("COURTYARD_TOKEN"), required=False)
    parser.add_argument("--behavior", default="echo", help="echo | script:<file.yaml> | manual")
    parser.add_argument("--open", dest="opening", help='opening move: "peer: first message"')
    parser.add_argument("--heartbeat", type=float, default=30.0, help="heartbeat seconds")
    args = parser.parse_args()
    if not args.name or not args.token:
        parser.error("--name and --token are required (or COURTYARD_AGENT_NAME/COURTYARD_TOKEN)")

    def _sigterm(*_args) -> None:
        raise KeyboardInterrupt  # so a `kill` still detaches cleanly

    signal.signal(signal.SIGTERM, _sigterm)

    behavior = build_behavior(args.behavior)
    dummy = Dummy(args.hub, args.name, args.token, behavior, args.heartbeat)
    try:
        summary = dummy.start()
    except (HubError, httpx.HTTPError, OSError) as exc:
        print(f"cannot attach to the hub at {args.hub}: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    print_summary(summary)

    try:
        if args.opening:
            peer, _, body = args.opening.partition(":")
            dummy.say(peer.strip(), body.strip())
        if isinstance(behavior, ManualBehavior):
            manual_repl(dummy, behavior)
        else:
            dummy.wait()
    except KeyboardInterrupt:
        pass
    finally:
        dummy.stop()
        print("detached.")


if __name__ == "__main__":
    cli()
