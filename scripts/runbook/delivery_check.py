"""Runbook check: the channel-flag report and the delivery-verification check
(items 33/34, D29/D30).

Runs against its OWN throwaway hub on a scratch database — never the dev hub —
because it starts a shift (a dev hub would open real terminals for any down
claude-code agent) and uses a short check timeout.

  1. attach with channel_flag=absent -> the agent listing carries the fact
     (the board raises the "cannot hear the hub" popup on it)
  2. verify-delivery -> the dummy receives the check envelope (printed: what a
     real model reads), the token is acked -> delivery_check: verified
  3. a second check, never acked -> after the timeout, delivery_check: failed
  4. a dummy attaching while a shift is active receives a check automatically

Needs the compose postgres up (`make db-up`). Run:
    uv run python scripts/runbook/delivery_check.py
"""

import os
import re
import subprocess
import sys
import time

from courtyard.common.client import ChannelReceiver, HubClient

PORT = 3634
HUB = f"http://127.0.0.1:{PORT}"
DB_NAME = "courtyard_delivery_rb"
PG_PORT = os.environ.get("COURTYARD_PG_PORT", "5432")
DB = f"postgresql://courtyard:courtyard@127.0.0.1:{PG_PORT}/{DB_NAME}"
VERIFY_TIMEOUT = "3"  # so the failed verdict shows in seconds, not a minute


def hr(title):
    print("\n" + "=" * 78 + f"\n{title}\n" + "=" * 78)


def psql(*statements, db="postgres"):
    subprocess.run(
        ["docker", "exec", "courtyard-postgres", "psql", "-U", "courtyard", "-d", db]
        + [arg for s in statements for arg in ("-c", s)],
        check=True,
        capture_output=True,
    )


def start_hub():
    env = {
        **os.environ,
        "DATABASE_URL": DB,
        "COURTYARD_PORT": str(PORT),
        "COURTYARD_VERIFY_TIMEOUT_SECONDS": VERIFY_TIMEOUT,
        "COURTYARD_SWEEP_SECONDS": "0.5",
    }
    proc = subprocess.Popen(
        ["uv", "run", "courtyard-hub"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    admin = HubClient(HUB)
    for _ in range(100):
        try:
            admin._call("GET", "/api/health")
            return proc, admin
        except Exception:  # noqa: BLE001 - still booting; keep polling
            time.sleep(0.2)
    proc.terminate()
    sys.exit("the throwaway hub never came up")


def row(admin, name):
    return next(a for a in admin.agents() if a.name == name)


psql(f"DROP DATABASE IF EXISTS {DB_NAME}", f"CREATE DATABASE {DB_NAME}")
proc, admin = start_hub()
try:
    hr("1. THE CHANNEL FLAG (item 33): attach reports how the session was launched")
    _, token = admin.register_agent("deaf-dummy", "dummy", "launched without the flag")
    deaf = HubClient(HUB, "deaf-dummy", token)
    inbox = []
    receiver = ChannelReceiver(inbox.append)
    deaf.attach(receiver.endpoint, receiver.channel_token, "absent")
    a = row(admin, "deaf-dummy")
    print(f"status: {a.status}   channel_flag: {a.channel_flag}")
    print("-> on the board this raises the 'cannot hear the hub' popup and a red card foot")

    hr("2. THE DELIVERY CHECK (item 34): what the model receives, and the ack")
    admin.verify_delivery("deaf-dummy")
    time.sleep(0.3)
    check = inbox[-1]
    print("the check envelope, as a real model reads it:\n")
    print(check.rendered)
    print(f"\nwhile open: delivery_check = {row(admin, 'deaf-dummy').delivery_check}")
    tok = re.search(r'token "([^"]+)"', check.rendered).group(1)
    print(f"acking token {tok!r} -> {deaf.ack(tok)}")
    a = row(admin, "deaf-dummy")
    print(f"after ack: delivery_check = {a.delivery_check} at {a.delivery_checked_at}")

    hr(f"3. TIMEOUT: an unacked check fails after {VERIFY_TIMEOUT}s")
    admin.verify_delivery("deaf-dummy")
    print(f"sent; delivery_check = {row(admin, 'deaf-dummy').delivery_check}")
    time.sleep(float(VERIFY_TIMEOUT) + 2)
    print(f"after the timeout: delivery_check = {row(admin, 'deaf-dummy').delivery_check}")
    print("-> the card foot warns 'delivery check failed'")

    hr("4. AUTOMATIC CHECK: a session beginning during a shift is checked unasked")
    admin._call("POST", "/api/shift/start")
    _, token2 = admin.register_agent("late-dummy", "dummy", "attaches mid-shift")
    late = HubClient(HUB, "late-dummy", token2)
    inbox2 = []
    receiver2 = ChannelReceiver(inbox2.append)
    late.attach(receiver2.endpoint, receiver2.channel_token, "present")
    time.sleep(0.3)
    print(f"pushes received on attach: {len(inbox2)} (the delivery check, no request made)")
    print(f"delivery_check = {row(admin, 'late-dummy').delivery_check}")
    admin._call("POST", "/api/shift/end", {"force": True})

    receiver.stop()
    receiver2.stop()
    deaf.close()
    late.close()
    print("\nAll four checkpoints shown.")
finally:
    admin.close()
    proc.terminate()
    proc.wait(timeout=10)
    psql(f"DROP DATABASE IF EXISTS {DB_NAME}")
    print("(throwaway hub stopped, scratch database dropped.)")
