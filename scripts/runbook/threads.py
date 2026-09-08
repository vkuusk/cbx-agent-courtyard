"""Runbook check: D34 — threads, the quant of conversation (design threads.md).

  1. Open and continue: the first message on a quiet line opens a thread; replies and
     follow-ups continue it. The line carries its one open thread.
  2. Boundary declaration: a declared new ask (new_thread) while the thread is open is
     refused like a turn violation — the refusal text is printed for reading.
  3. Close: only the initiator closes; the peer's attempt is refused. The answer's
     envelope points the initiator (and only the initiator) at the close tool. The
     close resolves the line's reply obligation and the peer gets the fixed system
     line. The next ask opens a fresh thread.
  4. Expiry: end shift marks the open thread `expired` with a system entry. GUARDED —
     skipped unless this hub has no other non-idle lines and no real claude-code agent
     is down (same guards as expire_and_rearm.py).

Run against a hub started with `make run`:
    uv run python scripts/runbook/threads.py
"""

import os
import time

from courtyard.common.client import HubClient, HubError

HUB = os.environ.get("COURTYARD_HUB_URL", "http://127.0.0.1:2626")
DEAD_ENDPOINT = "http://127.0.0.1:9/push"  # nothing listens: deliveries wait for the pull


def hr(title):
    print("\n" + "=" * 78 + f"\n{title}\n" + "=" * 78)


admin = HubClient(HUB)
stamp = str(time.time_ns())[-7:]
a_name, b_name = f"thr-a-{stamp}", f"thr-b-{stamp}"
_, a_token = admin.register_agent(a_name, "dummy", "runbook initiator")
_, b_token = admin.register_agent(b_name, "dummy", "runbook peer")
a = HubClient(HUB, name=a_name, token=a_token)
b = HubClient(HUB, name=b_name, token=b_token)
line = admin.link(a_name, b_name)
admin.set_mode(line.id, "auto_pass")  # no gate stops here: threads are the subject
print(f"registered throwaway dummies {a_name} and {b_name} (their line set to auto-pass)")


def cleanup():
    for client, name in ((a, a_name), (b, b_name)):
        client.close()
        admin._call("DELETE", f"/api/agents/{name}")
    admin.close()
    print("\n(cleaned up the throwaway dummies; their line went to the archive.)")


hr("1. OPEN & CONTINUE  (first message opens; replies and follow-ups continue)")
ask = a.send(b_name, "which port does the staging db use?")
print(f"a's ask        : seq {ask.seq}, thread {ask.thread_id}")
b.inbox()
answer = b.send(a_name, "5433 — it moved with the compose split.")
print(f"b's answer     : seq {answer.seq}, thread {answer.thread_id}   <- same thread")
(thread,) = admin.line_threads(ask.line_id)
print(f"threads on line: 1 — state {thread.state}, opened by {thread.opened_by_name}")

hr("2. BOUNDARY DECLARATION  (a declared new ask is refused while the thread is open)")
try:
    a.send(b_name, "unrelated: rotate the api key please", new_thread=True)
    print("REFUSAL MISSING — that is a bug")
except HubError as exc:
    print(f"refused        : {exc}")

hr("3. CLOSE  (initiator only; the envelope points at the tool; the peer is told)")
(delivered,) = a.inbox()
pointer = "courtyard_close_thread" in (delivered.rendered or "")
print(f"answer envelope points a at the close tool : {pointer}")
try:
    b.close_thread(a_name)
    print("peer close accepted — that is a bug")
except HubError as exc:
    print(f"peer's close refused : {exc}")
closed = a.close_thread(b_name)
print(f"initiator's close    : thread state {closed.state}, ended {closed.ended_at}")
line = next(ln for ln in admin.lines() if ln.id == ask.line_id)
print(f"line after close     : state {line.state}, open thread {line.open_thread}")
(notice,) = b.inbox()
print(f"the peer's notice    : [{notice.kind}] {notice.body}")

second = a.send(b_name, "now the unrelated ask: rotate the api key please", new_thread=True)
states = [t.state for t in admin.line_threads(ask.line_id)]
print(f"next ask             : thread {second.thread_id}")
print(f"threads on line      : {states}   <- one closed, one open")

hr("4. EXPIRY  (end shift marks the open thread expired)")
# Guards: a forced end closes the books on EVERY non-idle line and every open thread,
# and Start shift opens real terminals for claude-code agents that are down.
ours = str(ask.line_id)
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

expired = next(t for t in admin.line_threads(ask.line_id) if str(t.id) == str(second.thread_id))
entry = next((m for m in admin.line_messages(ask.line_id) if "open thread expired" in m.body), None)
print(f"open thread    : state {expired.state}   (the closed one is untouched)")
print(f"system entry   : {entry.body if entry else 'MISSING — that is a bug'}")

cleanup()
