"""Step-2 demo: two scripted puppets converse through the hub, held and released by the
gate; then you play an agent yourself from a second terminal.

    make demo         # or: uv run python scripts/demo.py
    make demo-stop    # stop everything the demo started

Starts the hub only if one isn't already running on the configured port. Leaves hub and
puppets running afterwards so you can explore; re-running the demo starts a fresh cast
(unique name suffixes — history piles up on the board until `make db-nuke`).
"""

from __future__ import annotations

import argparse
import os
import secrets
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from courtyard.common.client import DEFAULT_HUB_URL, HubClient

ROOT = Path(__file__).resolve().parents[1]
DEMO_DIR = ROOT / ".demo"
HUB_URL = DEFAULT_HUB_URL

OPENING = (
    "Hey bob — the payments service is ready on branch feat/payments. Can you deploy it to staging?"
)


def say(text: str = "") -> None:
    print(text, flush=True)


def start_process(name: str, cmd: list[str]) -> None:
    log = (DEMO_DIR / f"{name}.log").open("w")
    proc = subprocess.Popen(
        cmd,
        stdout=log,
        stderr=subprocess.STDOUT,
        cwd=ROOT,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},  # logs must tail live
    )
    (DEMO_DIR / f"{name}.pid").write_text(str(proc.pid))


def stop_all() -> None:
    for pid_file in sorted(DEMO_DIR.glob("*.pid")):
        pid = int(pid_file.read_text())
        try:
            subprocess.run(["kill", str(pid)], check=False, capture_output=True)
            say(f"stopped {pid_file.stem} (pid {pid})")
        finally:
            pid_file.unlink()


def stop_puppets() -> None:
    """Retire the previous run's cast; keep the hub."""
    for pid_file in DEMO_DIR.glob("*.pid"):
        if pid_file.stem != "hub":
            subprocess.run(["kill", pid_file.read_text()], check=False, capture_output=True)
            pid_file.unlink()


def hub_is_up(admin: HubClient) -> bool:
    try:
        return admin._call("GET", "/api/health")["status"] == "ok"
    except Exception:  # noqa: BLE001 - any failure means "not up"
        return False


def ensure_hub(admin: HubClient) -> None:
    if hub_is_up(admin):
        say(f"hub already running at {HUB_URL} — using it")
        return
    say(f"starting the hub at {HUB_URL} (log: .demo/hub.log)")
    start_process("hub", ["uv", "run", "courtyard-hub"])
    deadline = time.monotonic() + 30
    while not hub_is_up(admin):
        if time.monotonic() > deadline:
            sys.exit("hub did not become healthy; see .demo/hub.log")
        time.sleep(0.3)


def wait_for(predicate, timeout: float, what: str):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.25)
    sys.exit(f"timed out waiting for {what}")


def print_transcript(admin: HubClient, line_id) -> None:
    say()
    say("─" * 72)
    say("the full line history, from the hub:")
    for m in admin.line_messages(line_id):
        who = f"{m.sender_name or 'hub'} → {m.recipient_name or 'board'}"
        say(f"  {m.seq}. [{m.kind}, {m.status}] {who}")
        say(f"     {m.body}")
        if m.gate_verdict:
            note = f" — note: {m.gate_note}" if m.gate_note else ""
            say(f"     (gate: {m.gate_verdict}{note})")
    say("─" * 72)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stop", action="store_true", help="stop demo hub and puppets")
    args = parser.parse_args()
    DEMO_DIR.mkdir(exist_ok=True)
    if args.stop:
        stop_all()
        return

    stop_puppets()
    admin = HubClient(HUB_URL)
    ensure_hub(admin)

    stale = admin.pending()
    for message in stale:  # a previous run's cast may have died mid-gate
        admin.decide(message.id, "reject", "stale demo leftover, cleared on demo restart")
    if stale:
        say(
            f"cleared {len(stale)} stale gate entr{'y' if len(stale) == 1 else 'ies'} "
            "left by previous demo runs"
        )

    suffix = secrets.token_hex(2)
    alice_name, bob_name = f"alice-{suffix}", f"bob-{suffix}"
    say(f"\nregistering two puppets: {alice_name} (coding) and {bob_name} (infra)")
    _, alice_token = admin.register_agent(
        alice_name, "puppet", "coding agent working on the payments service"
    )
    _, bob_token = admin.register_agent(
        bob_name, "puppet", "infra agent owning the staging and prod clusters"
    )

    say(f"\n  ▶ open {HUB_URL}/ in your browser now to watch the board live\n")
    say("launching them as separate processes (logs: .demo/alice.log, .demo/bob.log)")
    puppet = ["uv", "run", "courtyard-puppet", "--hub", HUB_URL, "--heartbeat", "5"]
    start_process(
        "bob",
        [
            *puppet,
            "--name",
            bob_name,
            "--token",
            bob_token,
            "--behavior",
            "script:scripts/demo/bob.yaml",
        ],
    )
    time.sleep(1.0)  # bob must be listening before alice's opening move
    start_process(
        "alice",
        [
            *puppet,
            "--name",
            alice_name,
            "--token",
            alice_token,
            "--behavior",
            "script:scripts/demo/alice.yaml",
            "--open",
            f"{bob_name}: {OPENING}",
        ],
    )

    say("\nalice sends her opening move — the line is supervised, so it stops at the gate:")
    (pending,) = wait_for(
        lambda: [m for m in admin.pending() if m.sender_name == alice_name],
        15,
        "the opening to reach the gate",
    )
    say(f'  pending: {pending.sender_name} → {pending.recipient_name}: "{pending.body[:80]}…"')

    say("\nthe operator flips the line to auto_pass, then approves the held opening —")
    say("everything after this flows without supervision:")
    admin.set_mode(pending.line_id, "auto_pass")
    admin.decide(pending.id, "approve", "opening the line — carry on without me")

    say("\nwatching the conversation run by itself…")
    seen = 0

    def conversation_done():
        nonlocal seen
        messages = [m for m in admin.line_messages(pending.line_id) if m.kind == "message"]
        for m in messages[seen:]:
            say(f"  {m.sender_name}: {m.body}")
        seen = len(messages)
        return len(messages) >= 6 and all(m.status == "delivered" for m in messages)

    wait_for(conversation_done, 30, "the 6-message conversation to finish")
    print_transcript(admin, pending.line_id)

    # -- phase 2: the supervised experience — the architect works the gate ------------
    dev_name, ops_name = f"dev-{suffix}", f"ops-{suffix}"
    _, dev_token = admin.register_agent(
        dev_name, "puppet", "dev puppet asking for risky things (gate demo)"
    )
    _, ops_token = admin.register_agent(ops_name, "puppet", "ops puppet guarding prod (gate demo)")
    start_process(
        "ops",
        [
            *puppet,
            "--name",
            ops_name,
            "--token",
            ops_token,
            "--behavior",
            "script:scripts/demo/gated-ops.yaml",
        ],
    )
    time.sleep(1.0)
    start_process(
        "dev",
        [
            *puppet,
            "--name",
            dev_name,
            "--token",
            dev_token,
            "--behavior",
            "script:scripts/demo/gated-dev.yaml",
            "--open",
            f"{ops_name}: I want to run schema migration 0042 on prod tonight — can I go ahead?",
        ],
    )
    say(f"""
{"─" * 72}
Phase 2 — the gate is yours. A second pair ({dev_name} ↔ {ops_name}) just started
on a SUPERVISED line: every message now waits for you in the browser.

  {HUB_URL}/#/gate

Things to try, in any order — the puppets react to your verdicts:

  · approve with a note      — your note is delivered to the recipient as an operator note
  · return with a comment    — {dev_name} is scripted to send a REVISED request
  · reject with a reason     — {dev_name} is scripted to back off politely
  · click the mode pill      — flips the line to auto-pass mid-conversation (and back)
  · watch the tab title      — "(N) Agent Courtyard" whenever something awaits you
  · open their line and use the note box at the bottom (default: to both) — then
    `tail .demo/dev.log .demo/ops.log` to see both puppets receive your insertion
""")

    # -- phase 3: the architect plays an agent ---------------------------------------
    guest_name, concierge_name = f"guest-{suffix}", f"concierge-{suffix}"
    _, guest_token = admin.register_agent(guest_name, "puppet", "played live by the operator")
    _, concierge_token = admin.register_agent(
        concierge_name, "puppet", "echo puppet that acknowledges everything"
    )
    start_process(
        "concierge",
        [*puppet, "--name", concierge_name, "--token", concierge_token, "--behavior", "echo"],
    )

    say(f"""{"─" * 72}
Phase 3 — you as a participant, straight from the browser:

  On the Board, click "message an agent…", pick {concierge_name}, and say hello.
  Your line with it is ungated (operator lines never pass the gate); the echo reply
  lands in your Inbox tab — watch the badge and the tab title.

Or play a full agent from a second terminal instead:

  uv run courtyard-puppet --name {guest_name} --token {guest_token} --behavior manual

Everything keeps running for exploring; `make demo-stop` shuts it all down.""")
    admin.close()


if __name__ == "__main__":
    signal.signal(signal.SIGINT, lambda *_: sys.exit(1))
    main()
