"""Runbook check: D24 — end shift closes the books; incidents re-deliver (design §8.1, §6.4).

  1. R1 re-arm: a message delivered to a previous session and never answered is flipped
     back to queued on the agent's next attach and re-delivered, with a "redelivered"
     system entry. Self-contained: two throwaway dummies on their own line.
  2. Expiry: ending the shift releases the non-idle line and marks the unanswered message
     `expired` (kept in history). GUARDED — skipped unless this hub has no other non-idle
     lines (a forced end would close the books on YOUR conversations too) and no real
     claude-code agent is down (starting the shift would open real terminals).

Run against a hub started with `make run`:
    uv run python scripts/runbook/expire_and_rearm.py
"""

import os
import time

from courtyard.common.client import HubClient, HubError

HUB = os.environ.get("COURTYARD_HUB_URL", "http://127.0.0.1:2626")
DEAD_ENDPOINT = "http://127.0.0.1:9/push"  # nothing listens: backlog stays queued for the pull


def hr(title):
    print("\n" + "=" * 78 + f"\n{title}\n" + "=" * 78)


admin = HubClient(HUB)
stamp = str(time.time_ns())[-7:]
a_name, b_name = f"exp-a-{stamp}", f"exp-b-{stamp}"
_, a_token = admin.register_agent(a_name, "dummy", "runbook sender")
b_agent, b_token = admin.register_agent(b_name, "dummy", "runbook recipient")
a = HubClient(HUB, name=a_name, token=a_token)
b = HubClient(HUB, name=b_name, token=b_token)
print(f"registered throwaway dummies {a_name} and {b_name}")


def cleanup():
    for client, name in ((a, a_name), (b, b_name)):
        client.close()
        admin._call("DELETE", f"/api/agents/{name}")
    admin.close()
    print("\n(cleaned up the throwaway dummies; their line went to the archive.)")


hr("1. R1 RE-ARM  (delivered to a previous session, unanswered -> requeued on attach)")
msg = a.send(b_name, "are you there?")
admin.decide(msg.id, "approve")
(pulled,) = b.inbox()  # "session 1" reads it and dies without answering
print(f"delivered to session 1 : seq {pulled.seq}, status {pulled.status}")

summary = b.attach(DEAD_ENDPOINT, "runbook-ct")  # "session 2" starts
print(f"attach summary queued  : {summary.queued}   <- the obligation rides the backlog again")
history = admin.line_messages(msg.line_id)
rearmed = next(m for m in history if m.id == msg.id)
note = next((m for m in history if m.kind == "system" and "redelivered" in m.body), None)
print(f"message status         : {rearmed.status}   (was delivered; re-armed)")
print(f"system entry           : {note.body if note else 'MISSING — that is a bug'}")
(pulled,) = b.inbox()
print(f"delivered to session 2 : seq {pulled.seq}, status {pulled.status}")

hr("2. EXPIRY  (end shift releases the line, the unanswered message expires)")
# Guards: a forced end closes the books on EVERY non-idle line, and Start shift opens
# real terminals for claude-code agents that are down. Both must be clear on a dev hub.
ours = str(msg.line_id)
busy_others = [ln for ln in admin.lines() if ln.state != "idle" and str(ln.id) != ours]
down = [
    ag.name
    for ag in admin.agents()
    if ag.type == "claude-code" and not ag.removed_at and ag.workdir and ag.status != "connected"
]
if busy_others or down:
    if busy_others:
        print(f"SKIPPED: {len(busy_others)} other line(s) are mid-conversation on this hub —")
        print("a forced End shift would expire those too. Finish or release them first.")
    if down:
        print(f"SKIPPED: claude-code agent(s) down ({', '.join(down)}) — starting the shift")
        print("would open real terminals for them.")
    cleanup()
    raise SystemExit(0)

admin._call("POST", "/api/shift/start")
try:
    admin._call("POST", "/api/shift/end", {"force": False})
    print("end            : accepted without force — unexpected, the line was busy")
except HubError as exc:
    print(f"end refused    : {exc} -> forcing (only our throwaway line is mid-work)")
    admin._call("POST", "/api/shift/end", {"force": True})

line = next(ln for ln in admin.lines() if str(ln.id) == ours)
history = admin.line_messages(msg.line_id)
expired = next(m for m in history if m.id == msg.id)
entry = next((m for m in history if "expired at end of shift" in m.body), None)
print(f"line state     : {line.state}   (released)")
print(f"message status : {expired.status}   (kept in history, obligation gone)")
print(f"system entry   : {entry.body if entry else 'MISSING — that is a bug'}")

summary = b.attach(DEAD_ENDPOINT, "runbook-ct")
print(f"re-attach after expiry : queued {summary.queued}   <- expired is NOT re-armed")

cleanup()
