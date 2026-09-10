"""Runbook check: per-thread budgets (design threads.md §5 item 2, D34 - slice 2).

Runs against its OWN throwaway hub on a scratch database — never the dev hub — because
the check flips the courtyard-wide thread budget, and a tiny budget on a hub with real
agents would lock their live threads.

  1. the Admin default (12) and setting it to 2
  2. an exchange spends the budget; the follow-up is refused with `thread_locked`,
     the thread locks (committed despite the refusal), both sides get the durable
     system line, the line is idle
  3. the next ask opens a fresh thread — the line is never stuck
  4. a reply always passes, even past the budget (obligations stay dischargeable)
  5. returned messages do not count (they never reached anyone)
  6. operator threads are never locked, whatever the budget says
  7. budget 0 = unbudgeted

Needs the compose postgres up (`make db-up`). Run:
    uv run python scripts/runbook/thread_budget.py
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time

from courtyard.common.client import HubClient, HubError

PORT = 3637
HUB = f"http://127.0.0.1:{PORT}"
DB_NAME = "courtyard_threadbudget_rb"
PG_PORT = os.environ.get("COURTYARD_PG_PORT", "26432")
PG_CONTAINER = os.environ.get("COURTYARD_COMPOSE_PROJECT", "courtyard") + "-postgres"
DB = f"postgresql://courtyard:courtyard@127.0.0.1:{PG_PORT}/{DB_NAME}"


def hr(title):
    print("\n" + "=" * 78 + f"\n{title}\n" + "=" * 78)


def psql(*statements, db="postgres"):
    subprocess.run(
        ["docker", "exec", PG_CONTAINER, "psql", "-U", "courtyard", "-d", db]
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


psql(f"DROP DATABASE IF EXISTS {DB_NAME} WITH (FORCE)", f"CREATE DATABASE {DB_NAME}")
hub, admin = start_hub()
try:
    # D33: a current team is required before agents can register
    team_dir = tempfile.mkdtemp(prefix="runbook-team-")
    admin.set_current_team(admin.add_team(team_dir, "runbook").id)
    _, alice_token = admin.register_agent("alice", "dummy")
    _, bob_token = admin.register_agent("bob", "dummy")
    alice = HubClient(HUB, name="alice", token=alice_token)
    bob = HubClient(HUB, name="bob", token=bob_token)
    line = admin.link("alice", "bob")
    admin.set_mode(line.id, "auto_pass")  # no gate stops here: the budget is the subject

    hr("1. THE DIAL  (Admin default, then set to 2 for this check)")
    print(f"default thread_budget : {admin.settings()['thread_budget']}")
    admin.patch_settings({"thread_budget": 2})
    print(f"set to                : {admin.settings()['thread_budget']}")

    hr("2. THE BUDGET SPENDS AND THE THREAD LOCKS")
    ask = alice.send("bob", "which region is staging in?")
    bob.inbox()
    bob.send("alice", "eu-central-1.")
    alice.inbox()
    print("exchange made  : 2 messages — the budget is spent, the thread still open")
    try:
        alice.send("bob", "and production?")
        print("REFUSAL MISSING — that is a bug")
    except HubError as exc:
        print(f"follow-up      : refused\n  {exc}")
    (thread,) = admin.line_threads(ask.line_id)
    print(f"thread state   : {thread.state}   (the lock survived the refusal)")
    lines = {ln.id: ln for ln in admin.lines()}
    print(
        f"line           : state {lines[ask.line_id].state}, open thread "
        f"{lines[ask.line_id].open_thread}"
    )
    notices = [m for m in admin.line_messages(ask.line_id) if m.kind == "system"]
    print(
        f"both told      : {len(notices)} system lines, to "
        f"{sorted(m.recipient_name for m in notices)}"
    )
    print(f"  wording      : {notices[0].body}")

    hr("3. THE NEXT ASK OPENS A FRESH THREAD")
    second = alice.send("bob", "different topic: who owns the dns zone?")
    states = [t.state for t in admin.line_threads(ask.line_id)]
    print(f"send accepted  : thread {second.thread_id}")
    print(f"threads on line: {states}")
    bob.inbox()
    bob.send("alice", "the operator does.")
    alice.close_thread("bob")  # leave the line settled for the next checkpoints

    hr("4. A REPLY ALWAYS PASSES  (budget 1: the ask alone spends it)")
    admin.patch_settings({"thread_budget": 1})
    ask3 = alice.send("bob", "is the vpn cert renewed?")
    bob.inbox()
    reply = bob.send("alice", "yes, last tuesday.")
    print(
        f"bob's reply    : {reply.status} (message {2} of a budget-1 thread — "
        "obligations stay dischargeable)"
    )
    alice.inbox()
    alice.close_thread("bob")

    hr("5. RETURNED MESSAGES DO NOT COUNT")
    admin.set_mode(ask3.line_id, "supervised")
    held = alice.send("bob", "do the thing")
    admin.decide(held.id, "return", "which thing? reword it")
    revised = alice.send("bob", "rotate the grafana token, please")
    print(f"revised ask    : {revised.status} in the same thread {revised.thread_id}")
    print("  (a returned message never reached anyone; the revision is the same ask)")
    admin.decide(revised.id, "drop")  # tidy up; the thread expires with the check

    hr("6. OPERATOR THREADS ARE NEVER LOCKED  (budget still 1)")
    first = admin._call("POST", "/api/operator/send", {"to": "bob", "body": "status?"})
    bob.inbox()
    bob.send("operator", "all green.")
    followup = admin._call("POST", "/api/operator/send", {"to": "bob", "body": "and alice?"})
    print(f"operator's 2nd ask in one thread : {followup['status']}  <- unbudgeted (D9 analog)")

    hr("7. BUDGET 0 = UNBUDGETED")
    admin.patch_settings({"thread_budget": 0})
    bob.inbox()
    bob.send("operator", "alice is fine too.")
    print(f"thread_budget 0 accepted : {admin.settings()['thread_budget'] == 0}")
finally:
    shutil.rmtree(team_dir, ignore_errors=True)
    for client in (alice, bob, admin):
        client.close()
    hub.terminate()
    hub.wait(timeout=10)
    psql(f"DROP DATABASE IF EXISTS {DB_NAME} WITH (FORCE)")
    print("\n(throwaway hub stopped, scratch database dropped.)")
