"""Round-trip communications test: operator -> agent1 (real Claude Code) -> operator.

Drives the full production path with a real Claude Code session (cheap model by
default): ensure hub -> install the agent's config -> launch `claude` in a pty from the
agent's workdir -> wait for attach -> operator sends a nonce over the hub -> the channel
push must land in the session as a live turn -> the agent replies via courtyard_send ->
the reply reaches the operator's line.

This is deliberately NOT a pytest test (dashes in the name): it needs a live Claude Code
login, spends model tokens, and takes a minute+. Run it directly (or `make test-comms`):

    uv run python tests/communications/oper-agent1-oper.py [--agent …] [--model …]
        [--hub …] [--timeout …]

Defaults come from `communication-test-config.yml` next to this script (keys: hub,
agent1, model, timeout); a CLI flag overrides the file.

It starts a hub if none is running (and stops it after). On failure it prints the three
diagnostics that separate every failure class we have seen (feedback items 10/11):
  - the test message's hub status (queued = push failed; delivered = the adapter took it)
  - the session's channel verdict from Claude Code's MCP log ("registered" vs "skipped")
  - the tail of the live terminal screen
"""

from __future__ import annotations

import argparse
import fcntl
import os
import re
import secrets
import signal
import struct
import subprocess
import sys
import termios
import time
from pathlib import Path

import httpx
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from courtyard.common.client import HubClient, HubError

CONFIG_FILE = Path(__file__).with_name("communication-test-config.yml")

ANSI = re.compile(
    r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[=>()][B0]?|[\r\x00]"
)
MCP_LOG_ROOT = Path.home() / "Library/Caches/claude-cli-nodejs"

# The one launch form that registers the channel on current Claude Code (2.1.245; see
# feedback item 11 — 2.1.241 briefly required --channels, 2.1.245 reverted AND made the
# two-flag combo fail the allowlist check). Verified by probe on 2026-08-24.
CHANNEL_FLAGS = ["--dangerously-load-development-channels", "server:courtyard"]

# TUI dialogs we answer with Enter (the highlighted default) exactly once each.
# Matched with all whitespace removed: the TUI positions words with escape sequences,
# so the ANSI-cleaned text often has no spaces at all.
DIALOGS = [
    "Iamusingthisforlocaldevelopment",  # dev-channels consent
    "Yes,proceed",  # workdir trust
    "Yes,Itrustthisfolder",  # workdir trust (newer wording)
]


def hr(title: str) -> None:
    print("\n" + "=" * 78 + f"\n{title}\n" + "=" * 78, flush=True)


def clean(raw: bytes) -> str:
    return ANSI.sub("", raw.decode("utf-8", "replace"))


class ClaudeSession:
    """A real `claude` session on a pty; output collected, known dialogs auto-answered."""

    def __init__(self, workdir: str, model: str):
        self.workdir = workdir
        self.buf = b""
        self._answered: set[str] = set()
        self._master, slave = os.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 140, 0, 0))
        self.proc = subprocess.Popen(
            ["claude", *CHANNEL_FLAGS, "--model", model],
            cwd=workdir,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            start_new_session=True,
            # strip nesting markers: when this script itself runs inside a Claude Code
            # session, inherited CLAUDE_CODE_* vars change the child session's behaviour
            env={
                **{
                    k: v
                    for k, v in os.environ.items()
                    if not (k.startswith("CLAUDE_CODE_") or k == "CLAUDECODE")
                },
                "TERM": "xterm-256color",
            },
        )
        os.close(slave)
        os.set_blocking(self._master, False)

    def pump(self) -> None:
        """Drain pty output; answer any known dialog the first time it appears."""
        try:
            while True:
                chunk = os.read(self._master, 65536)
                if not chunk:
                    break
                self.buf += chunk
        except (BlockingIOError, OSError):
            pass
        screen = re.sub(r"\s+", "", clean(self.buf))
        for needle in DIALOGS:
            if needle in screen and needle not in self._answered:
                self._answered.add(needle)
                time.sleep(0.5)
                os.write(self._master, b"\r")
                print(f"  [answered dialog: {needle!r}]", flush=True)

    def tail(self, lines: int = 25) -> str:
        text = [ln for ln in clean(self.buf).splitlines() if ln.strip()]
        return "\n".join(text[-lines:])

    def stop(self) -> None:
        try:
            os.killpg(self.proc.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(self.proc.pid, signal.SIGKILL)
        os.close(self._master)


def channel_verdict(workdir: str, since: float) -> str:
    """What Claude Code's own MCP log says about the courtyard channel this session."""
    munged = "-" + str(Path(workdir).resolve()).strip("/").replace("/", "-")
    log_dir = MCP_LOG_ROOT / munged / "mcp-logs-courtyard"
    files = [f for f in log_dir.glob("*.jsonl") if f.stat().st_mtime >= since]
    for f in sorted(files, key=lambda f: f.stat().st_mtime, reverse=True):
        hits = re.findall(r"Channel notifications[^\"\\]*", f.read_text())
        if hits:
            return hits[-1]
    return "(no channel line in the MCP log yet)"


def load_defaults() -> dict:
    """Defaults, overlaid with communication-test-config.yml when it exists."""
    defaults = {
        "hub": "http://127.0.0.1:2626",
        "agent": "cbxorg-infra",
        "model": "haiku",
        "timeout": 240.0,
    }
    if CONFIG_FILE.exists():
        doc = yaml.safe_load(CONFIG_FILE.read_text()) or {}
        for yml_key, arg_key in (
            ("hub", "hub"),
            ("agent1", "agent"),
            ("model", "model"),
            ("timeout", "timeout"),
        ):
            if doc.get(yml_key) is not None:
                defaults[arg_key] = doc[yml_key]
    return defaults


def main() -> int:
    defaults = load_defaults()
    ap = argparse.ArgumentParser()
    ap.add_argument("--hub", default=defaults["hub"])
    ap.add_argument(
        "--agent", default=defaults["agent"], help="agent1: a registered claude-code agent"
    )
    ap.add_argument(
        "--model", default=defaults["model"], help="model for agent1's session (cheap by default)"
    )
    ap.add_argument(
        "--timeout",
        type=float,
        default=float(defaults["timeout"]),
        help="seconds to wait for the reply",
    )
    args = ap.parse_args()
    if CONFIG_FILE.exists():
        print(f"config: {CONFIG_FILE.name} (CLI flags override it)")

    admin = HubClient(args.hub)
    hub_proc: subprocess.Popen | None = None
    session: ClaudeSession | None = None
    started = time.time()

    def poll(seconds: float, what: str, fn):
        deadline = time.time() + seconds
        while time.time() < deadline:
            if session:
                session.pump()
            result = fn()
            if result:
                return result
            time.sleep(1.0)
        raise TimeoutError(what)

    try:
        hr("0. HUB")
        try:
            admin._call("GET", "/api/health")
            print("hub already running")
        except (HubError, httpx.HTTPError):
            print("starting a hub…")
            hub_proc = subprocess.Popen(
                ["uv", "run", "courtyard-hub"],
                cwd=Path(__file__).resolve().parents[2],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            poll(30, "hub did not come up", lambda: _ok(admin))

        hr("1. AGENT CONFIG")
        agent = next((a for a in admin.agents() if a.name == args.agent and not a.removed_at), None)
        assert agent, f"agent {args.agent!r} is not registered"
        assert agent.workdir, f"agent {args.agent!r} has no workdir"
        print(f"agent1: {agent.name} · workdir {agent.workdir} · model {args.model}")
        result = admin.install(agent.name)  # fresh .mcp.json + .claude/settings.local.json
        print(f"installed: {result['path']}\n           {result['settings_path']}")

        # a stuck line from earlier testing would block the operator's send (item 10)
        line = next(
            (
                ln
                for ln in admin.lines()
                if {ln.agent_a_name, ln.agent_b_name} == {"operator", agent.name}
            ),
            None,
        )
        if line and line.state != "idle":
            admin.release(line.id)
            print(f"released the operator line (was {line.state})")

        hr("2. LAUNCH  claude " + " ".join(CHANNEL_FLAGS) + f" --model {args.model}")
        session = ClaudeSession(agent.workdir, args.model)
        poll(
            90,
            "agent never reached status=connected (attach failed)",
            lambda: next(
                (a for a in admin.agents() if a.name == agent.name and a.status == "connected"),
                None,
            ),
        )
        print("attached: status=connected")
        time.sleep(3)
        session.pump()
        verdict = channel_verdict(agent.workdir, started)
        print(f"channel : {verdict}")

        hr("3. OPERATOR -> AGENT1 -> OPERATOR")
        nonce = secrets.token_hex(4)
        body = (
            f"Courtyard delivery test {nonce}: reply to the operator via the courtyard "
            f"with exactly: ACK {nonce}. Send only that reply; do nothing else."
        )
        sent = admin._call("POST", "/api/operator/send", {"to": agent.name, "body": body})
        line_id, my_seq = sent["line_id"], sent["seq"]
        print(f"sent seq {my_seq}: {body[:60]}…")

        last_status = [None]

        def find_reply():
            msgs = admin.line_messages(line_id)
            mine = next((m for m in msgs if m.seq == my_seq), None)
            if mine and mine.status != last_status[0]:
                last_status[0] = mine.status
                print(f"  test message status: {mine.status}", flush=True)
            return next(
                (
                    m
                    for m in msgs
                    if m.seq > my_seq and m.sender == agent.id and m.kind == "message"
                ),
                None,
            )

        reply = poll(
            args.timeout, f"no reply from {agent.name} within {args.timeout:.0f}s", find_reply
        )
        print(f"\nreply seq {reply.seq}: {reply.body[:80]}")
        ok = nonce in reply.body
        print("nonce echoed back" if ok else "!! reply does not contain the nonce")

        hr("PASS — full round trip: operator -> hub -> channel turn -> courtyard_send -> operator")
        return 0

    except (TimeoutError, AssertionError) as exc:
        hr(f"FAIL — {exc}")
        if session is not None:
            try:
                print(f"channel : {channel_verdict(session.workdir, started)}")
            except OSError as log_exc:
                print(f"channel : (could not read the MCP log: {log_exc})")
        if session:
            session.pump()
            print("\n--- last lines of the agent's terminal ---")
            print(session.tail())
        return 1
    finally:
        if session:
            session.stop()
        if hub_proc:
            hub_proc.terminate()
            try:
                hub_proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                hub_proc.kill()


def _ok(admin: HubClient):
    try:
        return admin._call("GET", "/api/health")
    except (HubError, httpx.HTTPError):
        return None


if __name__ == "__main__":
    sys.exit(main())
