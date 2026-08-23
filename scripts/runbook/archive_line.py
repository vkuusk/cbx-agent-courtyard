"""Runbook check: archiving line histories (design §5.7, D20).

  1. a conversation is archived on request: one document, the line continues empty + idle
  2. the archive can be read back and exported as JSON
  3. removing an agent archives its lines by itself and the lines are gone from the board

Run against a hub started with `make db-up && make run`:
    uv run python scripts/runbook/archive_line.py

Throwaway: two puppet registrations, removed at the end; the archives it made are deleted.
"""

import json
import time

from courtyard.common.client import HubClient

HUB = "http://127.0.0.1:2626"


def hr(title):
    print("\n" + "=" * 78 + f"\n{title}\n" + "=" * 78)


admin = HubClient(HUB)
suffix = str(time.time_ns())[-7:]
a_name, b_name = f"arch-a-{suffix}", f"arch-b-{suffix}"
_, a_token = admin.register_agent(a_name, "puppet", "runbook agent A")
_, b_token = admin.register_agent(b_name, "puppet", "runbook agent B")
a, b = HubClient(HUB, name=a_name, token=a_token), HubClient(HUB, name=b_name, token=b_token)

first = a.send(b_name, "shall we deploy v2 tonight?")
admin.decide(first.id, "approve", "fine by me")
reply = b.send(a_name, "yes — after the backup finishes")
admin.decide(reply.id, "approve")
line_id = first.line_id
before = admin.line_messages(line_id)
print(f"line {a_name} ↔ {b_name} has {len(before)} entries:")
for m in before:
    print(f"  {m.seq}. [{m.kind}] {m.sender_name or 'hub'}: {m.body}")

hr("1. ARCHIVE ON REQUEST  (POST /api/lines/{id}/archive)")
archive = admin.archive_line(line_id)
print(f"archive id   : {archive.id}")
print(f"reason       : {archive.reason}   messages: {archive.message_count}")
after = admin.line_messages(line_id)
print(f"line now     : {len(after)} entry -> [{after[0].kind}] {after[0].body}")
print(
    f"line state   : {admin._call('GET', f'/api/lines/{line_id}')['state']}   <- idle, ready to continue"
)

hr("2. READ IT BACK + EXPORT  (GET /api/archive/{id}, …/export)")
full = admin.archive(archive.id)
print(f"transcript   : {[m.body for m in full.transcript]}")
print(f"gate note kept: {full.transcript[0].gate_note!r}")
raw = admin._http.get(f"/api/archive/{archive.id}/export")
print(f"export       : HTTP {raw.status_code}, {raw.headers['content-disposition']}")
print(f"export is the same document: {json.loads(raw.text)['id'] == str(archive.id)}")

hr("3. REMOVAL ARCHIVES BY ITSELF  (DELETE /api/agents/{name})")
a.send(b_name, "one more thing")  # a fresh message on the continued line
admin._call("DELETE", f"/api/agents/{a_name}")
lines_left = [ln for ln in admin.lines() if ln.id == line_id]
print(f"line still on the board: {bool(lines_left)}   <- gone")
mine = [x for x in admin.archives() if a_name in (x.agent_a_name, x.agent_b_name)]
print(
    f"archives for {a_name}: {[(x.reason, x.message_count) for x in mine]}   <- the removal made the 2nd"
)

for x in mine:
    admin.delete_archive(x.id)
admin._call("DELETE", f"/api/agents/{b_name}")
for extra in [x for x in admin.archives() if b_name in (x.agent_a_name, x.agent_b_name)]:
    admin.delete_archive(extra.id)
a.close()
b.close()
admin.close()
print("\n(cleaned up the throwaway agents and their archives.)")
