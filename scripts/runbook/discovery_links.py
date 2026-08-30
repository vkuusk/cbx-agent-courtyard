"""Runbook check: discovery auto|manual (design §5.8, D22).

Runs against its OWN throwaway hub on a scratch database — never the dev hub — because
the check flips the courtyard-wide discovery setting, and doing that on a hub with real
agents attached would refuse their sends mid-run.

  1. auto (the default): a line forms on the first message between any pair
  2. flip to manual: an unlinked pair's send is refused with `not_linked`;
     the operator still reaches everyone, and everyone still answers the operator
  3. peers narrow to linked agents (plus the operator); the rendered text says so
  4. link two agents -> an idle line on the Defaults dial; now they talk
  5. unlink mid-conversation -> history archived (reason `unlinked`), line gone,
     the pair is unreachable again
  6. flip back to auto -> lines form freely again

Needs the compose postgres up (`make db-up`). Run:
    uv run python scripts/runbook/discovery_links.py
"""

import os
import subprocess
import sys
import time

from courtyard.common.client import HubClient, HubError

PORT = 3634
HUB = f"http://127.0.0.1:{PORT}"
DB_NAME = "courtyard_discovery_rb"
PG_PORT = os.environ.get("COURTYARD_PG_PORT", "5432")
DB = f"postgresql://courtyard:courtyard@127.0.0.1:{PG_PORT}/{DB_NAME}"


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
    env = {**os.environ, "DATABASE_URL": DB, "COURTYARD_PORT": str(PORT)}
    proc = subprocess.Popen(
        ["uv", "run", "courtyard-hub"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    client = HubClient(HUB)
    for _ in range(60):
        try:
            client._call("GET", "/api/health")
            return proc, client
        except (HubError, Exception):  # noqa: BLE001 - connection refused while booting
            time.sleep(0.2)
    proc.terminate()
    sys.exit("throwaway hub did not start")


def expect_refused(fn, code):
    try:
        fn()
        return f"ACCEPTED — that is a bug (expected {code})"
    except HubError as exc:
        marker = "OK" if exc.code == code else f"WRONG CODE (expected {code})"
        return f"refused with {exc.code}  <- {marker}"


psql(f"DROP DATABASE IF EXISTS {DB_NAME} WITH (FORCE)", f"CREATE DATABASE {DB_NAME}")
hub, admin = start_hub()
try:
    _, alice_token = admin.register_agent("alice", "puppet")
    _, bob_token = admin.register_agent("bob", "puppet")
    admin.register_agent("carol", "puppet")
    alice = HubClient(HUB, token=alice_token)
    bob = HubClient(HUB, token=bob_token)

    hr("1. AUTO (default): a line forms on first message")
    print(f"discovery         : {admin.settings()['discovery']}")
    message = alice.send("bob", "ping under auto")
    print(f"alice -> bob      : {message.status} (line formed on first send)")
    admin.decide(message.id, "drop")  # close the exchange; the line stays

    hr("2. MANUAL: unlinked pairs are refused; the operator is exempt")
    admin.patch_settings({"discovery": "manual"})
    print(f"alice -> carol    : {expect_refused(lambda: alice.send('carol', 'x'), 'not_linked')}")
    note = admin._call("POST", "/api/operator/send", {"to": "carol", "body": "you there?"})
    print(f"operator -> carol : {note['status']}  <- no link needed, ever")
    print(
        f"alice -> bob      : {alice.send('bob', 'still works').status}"
        "  <- the auto-era line IS the link (grandfathered)"
    )

    hr("3. PEERS FOLLOW THE LINES")
    view = alice._call("GET", "/api/agents/alice/peers")
    print(f"alice sees        : {[p['name'] for p in view['peers']]}  (carol filtered out)")
    print(
        f"rendered mentions : 'the operator manages the links' -> "
        f"{'the operator manages the links' in view['rendered']}"
    )

    hr("4. LINK bob <-> carol: an idle line, then they talk")
    line = admin.link("bob", "carol")
    print(f"link              : state={line.state} mode={line.mode} (the Defaults dial)")
    print(
        f"link again        : {expect_refused(lambda: admin.link('carol', 'bob'), 'already_linked')}"
    )
    print(
        f"link operator     : {expect_refused(lambda: admin.link('bob', 'operator'), 'not_allowed')}"
    )
    message = bob.send("carol", "hello, new neighbour")
    print(f"bob -> carol      : {message.status}")

    hr("5. UNLINK MID-CONVERSATION: history archived, permission gone")
    archive = admin.unlink(line.id)
    print(f"archive           : reason={archive.reason} messages={archive.message_count}")
    print(f"bob -> carol      : {expect_refused(lambda: bob.send('carol', 'x'), 'not_linked')}")

    hr("6. BACK TO AUTO: lines form freely again")
    admin.patch_settings({"discovery": "auto"})
    message = bob.send("carol", "as if nothing happened")
    print(f"bob -> carol      : {message.status} (a fresh line formed)")
finally:
    admin.close()
    hub.terminate()
    hub.wait()
    psql(f"DROP DATABASE IF EXISTS {DB_NAME} WITH (FORCE)")
    print("\n(throwaway hub stopped, scratch database dropped.)")
