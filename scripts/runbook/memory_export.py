"""Runbook check: hub memory, slice 4 — export and retention (design hub-memory.md
sections 6 and 8).

  1. two exchanges settle on one line, a third on another -> three case files
  2. the JSON Lines export: every record in full, one per line, oldest first;
     the search's filters (participant, since) narrow it for an incremental pull
  3. the first line is archived -> the archive counts the two case files that hang
     on its threads (the confirm on the Archive page names the same number)
  4. the archive is deleted -> those two case files go with it; the third line's
     case file and the note stay

Run against a hub started with `make run` (or pass --hub / COURTYARD_HUB_URL):
    uv run python scripts/runbook/memory_export.py

Throwaway: three time-suffixed agents, linked so it works under discovery `manual`
too; all three are removed at the end, with the archives and case files they leave.
Nothing courtyard-wide is changed; the note it writes is deleted with nothing (notes
have no delete) and stays, team-wide, marked as this script's.
"""

import argparse
import os
import time

from courtyard.common.client import HubClient

parser = argparse.ArgumentParser()
parser.add_argument("--hub", default=os.environ.get("COURTYARD_HUB_URL", "http://127.0.0.1:2626"))
HUB = parser.parse_args().hub


def hr(title):
    print("\n" + "=" * 78 + f"\n{title}\n" + "=" * 78)


admin = HubClient(HUB)
suffix = str(time.time_ns())[-7:]
names = {"infra": f"infra-{suffix}", "tf": f"tf-{suffix}", "db": f"db-{suffix}"}
tokens = {}
for key, domain in (
    ("infra", "the AWS estate"),
    ("tf", "terraform modules"),
    ("db", "postgres databases"),
):
    _, tokens[key] = admin.register_agent(names[key], "dummy", f"runbook {key}", domain)
as_ = {key: HubClient(HUB, name=names[key], token=tokens[key]) for key in names}
admin.link(names["infra"], names["tf"])
admin.link(names["infra"], names["db"])
print(f"registered {', '.join(names.values())} (dummies, linked infra-tf and infra-db)")


def approve_all():
    for m in admin.pending():
        if m.sender_name in names.values():
            admin.decide(m.id, "approve")


def settle(asker, answerer, ask, answer):
    q = as_[asker].send(names[answerer], ask, new_thread=True)
    approve_all()
    as_[answerer].inbox()
    as_[answerer].send(names[asker], answer)
    approve_all()
    as_[asker].inbox()
    as_[asker].close_thread(names[answerer])
    return q.line_id


hr("1. THREE EXCHANGES SETTLE  -> three case files")
line_tf = settle("infra", "tf", "which module pins provider 5?", "vpc 3.2 pins aws provider 5")
settle("infra", "tf", "and ipv6?", "enable_ipv6 = true since v3")
line_db = settle("infra", "db", "which postgres do we run?", "postgres 17 since the migration")
mine = [r for r in admin.memory_export() if any(p.name in names.values() for p in r.participants)]
print(f"case files of this run: {len(mine)}   (expected 3)")

hr("2. THE EXPORT  (GET /api/memory/export, JSON Lines)")
note = admin.memory_note(f"runbook memory_export {suffix}: standing guidance, team-wide")
everything = admin.memory_export()
print(f"records in the whole export: {len(everything)}  (every record the hub holds, oldest first)")
print(
    f"oldest first?   : {[r.created_at for r in everything] == sorted(r.created_at for r in everything)}"
)
print(f"full documents? : {all(r.document is not None for r in everything if r.kind == 'case')}")
print(f"the note is in  : {any(r.id == note.id for r in everything)}   (status {note.status})")
for_db = admin.memory_export(participant=names["db"])
print(f"participant={names['db']}: {[r.resolution for r in for_db]}   (expected the postgres one)")
since = mine[-1].created_at.isoformat()
later = admin.memory_export(since=since)
print(f"since={since}: {len(later)} record(s)   (the last case file and the note)")

hr("3. AN ARCHIVE COUNTS ITS CASE FILES")
archive = admin.archive_line(line_tf)
print(
    f"archived {archive.agent_a_name} <-> {archive.agent_b_name}: {archive.message_count} messages"
)
print(f"case_files      : {archive.case_files}   (expected 2: both threads of that line)")
listed = next(a for a in admin.archives() if a.id == archive.id)
print(f"in the listing  : {listed.case_files}   (what the Archive page's delete confirm names)")

hr("4. DELETING THE ARCHIVE TAKES THEM WITH IT")
admin.delete_archive(archive.id)
left = [r for r in admin.memory_export() if any(p.name in names.values() for p in r.participants)]
print(f"case files of this run left: {len(left)}   (expected 1, the {names['db']} one)")
print(f"which           : {[r.resolution for r in left]}")
print(f"the note stayed : {any(r.id == note.id for r in admin.memory_export())}   (expected True)")

for key in names:
    as_[key].close()
for name in names.values():
    admin.remove_agent(name)
for a in admin.archives():
    if a.agent_a_name in names.values() or a.agent_b_name in names.values():
        admin.delete_archive(a.id)
admin.close()
print(
    "\n(cleaned up the throwaway agents and their archives, and with them the last case"
    " file; the team-wide note stays: notes have no delete)"
)
