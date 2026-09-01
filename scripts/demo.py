"""Step-2 demo: two scripted dummies converse through the hub, held and released by the
gate; then you play an agent yourself from a second terminal.

    make demo         # or: uv run python scripts/demo.py
    make demo-stop    # stop everything the demo started

Starts the hub only if one isn't already running on the configured port. Leaves hub and
dummies running afterwards so you can explore. The cast cleans up after itself: both
`--stop` and a re-run remove the previous run's dummies from the board (their lines are
archived on removal, and those throwaway archives are deleted too) — the board looks the
way it did before the demo.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from courtyard.common.client import DEFAULT_HUB_URL, HubClient, HubError

ROOT = Path(__file__).resolve().parents[1]
DEMO_DIR = ROOT / ".demo"
HUB_URL = os.environ.get("COURTYARD_HUB_URL", DEFAULT_HUB_URL)
CHROME = os.environ.get(
    "COURTYARD_CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
)

CAST_FILE_NAME = "cast.json"  # in DEMO_DIR: the registered dummy names of the last run

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


def stop_dummies() -> None:
    """Retire the previous run's cast; keep the hub."""
    for pid_file in DEMO_DIR.glob("*.pid"):
        if pid_file.stem != "hub":
            subprocess.run(["kill", pid_file.read_text()], check=False, capture_output=True)
            pid_file.unlink()


def record_cast(names: list[str]) -> None:
    (DEMO_DIR / CAST_FILE_NAME).write_text(json.dumps(names))


def cleanup_cast(admin: HubClient) -> None:
    """Take the previous run's cast off the board: remove each dummy (its lines are
    archived, design §5.7) and delete the archives the demo produced — throwaway
    transcripts, not records anyone wants. Needs the hub up; otherwise the cast file
    stays for the next chance."""
    cast_file = DEMO_DIR / CAST_FILE_NAME
    if not cast_file.exists():
        return
    names = set(json.loads(cast_file.read_text()))
    if names and not hub_is_up(admin):
        return
    removed = 0
    for name in sorted(names):
        try:
            admin.remove_agent(name)
            removed += 1
        except HubError:
            pass  # already gone (db-nuke, manual removal)
    for archive in admin.archives():
        if archive.agent_a_name in names or archive.agent_b_name in names:
            admin.delete_archive(archive.id)
    cast_file.unlink()
    if removed:
        say(f"cleaned the previous demo cast off the board ({removed} dummies)")


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


def link_supervised(admin: HubClient, a: str, b: str) -> None:
    """The demo's pairs must talk whatever the operator's saved settings say: pre-create
    their line (a link, design §5.8 — legal under either discovery mode) and pin it
    supervised (the phases rely on the gate holding the opening). Without this, a dev
    hub left on Discovery `manual` refuses the dummies' sends as `not_linked`."""
    line = admin.link(a, b)
    admin.set_mode(line.id, "supervised")


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
    parser.add_argument("--stop", action="store_true", help="stop demo hub and dummies")
    parser.add_argument(
        "--chrome", action="store_true", help="open the board in its own Chrome window"
    )
    args = parser.parse_args()
    DEMO_DIR.mkdir(exist_ok=True)
    admin = HubClient(HUB_URL)
    if args.stop:
        stop_dummies()
        cleanup_cast(admin)  # while the hub, whoever started it, is still up
        stop_all()
        admin.close()
        return

    stop_dummies()
    ensure_hub(admin)
    cleanup_cast(admin)
    if args.chrome:
        try:
            subprocess.Popen(
                [CHROME, f"--app={HUB_URL}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            say("\n  ▶ the board opens in its own Chrome window — watch it live\n")
        except OSError:
            say(f"could not launch Chrome at {CHROME!r} — open {HUB_URL}/ yourself")
            args.chrome = False

    stale = admin.pending()
    for message in stale:  # a previous run's cast may have died mid-gate
        admin.decide(message.id, "drop", "stale demo leftover, cleared on demo restart")
    if stale:
        say(
            f"cleared {len(stale)} stale gate entr{'y' if len(stale) == 1 else 'ies'} "
            "left by previous demo runs"
        )

    suffix = secrets.token_hex(2)
    alice_name, bob_name = f"alice-{suffix}", f"bob-{suffix}"
    say(f"\nregistering two dummies: {alice_name} (coding) and {bob_name} (infra)")
    _, alice_token = admin.register_agent(
        alice_name, "dummy", "coding agent working on the payments service"
    )
    _, bob_token = admin.register_agent(
        bob_name, "dummy", "infra agent owning the staging and prod clusters"
    )
    cast = [alice_name, bob_name]
    record_cast(cast)  # incrementally: a failed run's partial cast still gets cleaned
    link_supervised(admin, alice_name, bob_name)

    if not args.chrome:
        say(f"\n  ▶ open {HUB_URL}/ in your browser now to watch the board live\n")
    say("launching them as separate processes (logs: .demo/alice.log, .demo/bob.log)")
    dummy = ["uv", "run", "courtyard-dummy", "--hub", HUB_URL, "--heartbeat", "5"]
    start_process(
        "bob",
        [
            *dummy,
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
            *dummy,
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
        dev_name, "dummy", "dev dummy asking for risky things (gate demo)"
    )
    _, ops_token = admin.register_agent(ops_name, "dummy", "ops dummy guarding prod (gate demo)")
    cast += [dev_name, ops_name]
    record_cast(cast)
    link_supervised(admin, dev_name, ops_name)
    start_process(
        "ops",
        [
            *dummy,
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
            *dummy,
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

  {HUB_URL}/  — their wire turns amber, "held at the gate": click it

Things to try, in any order — the dummies react to your verdicts (the comment field
sits right under the held message; what you type rides along with the verdict):

  · approve with a comment   — it is delivered to the recipient as an operator note
  · return with a comment    — {dev_name} is scripted to send a REVISED request
  · drop with a reason       — {dev_name} is scripted to back off politely
  · "switch to auto-pass"    — in the pane header, flips the line mid-conversation (and back)
  · watch the tab title      — "(N) Agent Courtyard" whenever something awaits you
""")

    # -- phase 3: the architect plays an agent ---------------------------------------
    guest_name, concierge_name = f"guest-{suffix}", f"concierge-{suffix}"
    _, guest_token = admin.register_agent(guest_name, "dummy", "played live by the operator")
    _, concierge_token = admin.register_agent(
        concierge_name, "dummy", "echo dummy that acknowledges everything"
    )
    cast += [guest_name, concierge_name]
    record_cast(cast)
    link_supervised(admin, guest_name, concierge_name)
    start_process(
        "concierge",
        [*dummy, "--name", concierge_name, "--token", concierge_token, "--behavior", "echo"],
    )

    say(f"""{"─" * 72}
Phase 3 — you as a participant, straight from the browser:

  On the Courtyard page, click the {concierge_name} rectangle and type in the box at the bottom.
  Your line with it is ungated (operator lines never pass the gate); the echo reply
  shows up in the pane and as "1 new" on the rectangle — watch the tab title too.

Or play a full agent from a second terminal instead:

  uv run courtyard-dummy --name {guest_name} --token {guest_token} --behavior manual

Everything keeps running for exploring; `make demo-stop` shuts it all down.""")
    admin.close()


if __name__ == "__main__":
    signal.signal(signal.SIGINT, lambda *_: sys.exit(1))
    main()
