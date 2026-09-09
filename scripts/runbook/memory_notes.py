"""Runbook check: hub memory, slice 2 — notes (design hub-memory.md sections 4, 5, 8).

  1. an agent leaves a note for its line (supervised) -> it waits for the operator;
     nobody can recall it yet, the author's tool result says so
  2. the operator returns it with a comment -> the author gets a hub notice on the
     operator's line; a second note is approved -> memory for that line's two agents,
     and NOT for a third agent
  3. a team-wide note from an agent waits even on an auto-pass line; approved, it
     reaches everyone
  4. the operator's own note is accepted at once, team-wide by default

Run against a hub started with `make run` (or pass --hub / COURTYARD_HUB_URL):
    uv run python scripts/runbook/memory_notes.py

Throwaway: three time-suffixed dummies, linked so the check runs under discovery
`manual` too; removed at the end with their archives. Nothing courtyard-wide changes.
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
names = {"infra": f"infra-{suffix}", "tf": f"tf-{suffix}", "argo": f"argo-{suffix}"}
tokens = {}
for key, domain in (("infra", "the AWS estate"), ("tf", "terraform modules"), ("argo", "argocd")):
    _, tokens[key] = admin.register_agent(names[key], "dummy", f"runbook {key}", domain)
as_ = {key: HubClient(HUB, name=names[key], token=tokens[key]) for key in names}
line = admin.link(names["infra"], names["tf"])
print(f"registered {', '.join(names.values())}; line infra-tf is {line.mode}")

hr("1. A NOTE ON A SUPERVISED LINE WAITS  (what courtyard_note tells the author)")
first = as_["tf"].note("always use latest", peer=names["infra"])
print(first.rendered)
print(f"\nstatus       : {first.status}   (expected pending)")
pending = [n for n in admin.memory_pending() if n.id == first.id]
print(f"on the operator's pending list: {bool(pending)}")
view = as_["infra"].recall("latest")
print(
    f"peer recalls it already?       : {any(r.id == first.id for r in view.records)}   (expected False)"
)

hr("2. RETURN WITH A COMMENT, THEN APPROVE ANOTHER")
admin.memory_decide(first.id, "return", "too vague: which module, which version?")
notices = as_["tf"].inbox()
print("the author's hub notice:")
for m in notices:
    print(f"  [{m.kind}] {m.body}")
second = as_["tf"].note("pin aws provider 5 in every module", peer=names["infra"])
accepted = admin.memory_decide(second.id, "approve")
print(
    f"\nsecond note  : {accepted.status}; nothing lands on the author for an approve: {as_['tf'].inbox() == []}"
)
for key in ("infra", "tf", "argo"):
    hits = as_[key].recall("aws provider")
    print(f"{names[key]:>16} recalls it: {any(r.id == second.id for r in hits.records)}")
print("(the line's two agents yes, the third agent no: a line's note is that line's)")
print("\nwhat infra's courtyard_recall prints:")
print(as_["infra"].recall("aws provider").rendered)

hr("3. A TEAM-WIDE NOTE WAITS EVEN ON AN AUTO-PASS LINE, THEN REACHES EVERYONE")
admin.set_mode(line.id, "auto_pass")
scoped = as_["tf"].note("module 3.2 is the floor", peer=names["infra"])
print(f"line note on auto-pass : {scoped.status}   (expected accepted, no gate)")
team = as_["tf"].note("we never force-push shared branches", team_wide=True)
print(f"team-wide note         : {team.status}   (expected pending)")
admin.memory_decide(team.id, "approve")
hits = as_["argo"].recall("force-push")
print(f"third agent recalls it : {any(r.id == team.id for r in hits.records)}   (expected True)")
admin.set_mode(line.id, "supervised")

hr("4. THE OPERATOR'S OWN NOTE")
mine = admin.memory_note("ask before deleting anything in prod")
print(f"status: {mine.status}, scope: {mine.scope}, author: {mine.author_name}")
print(as_["argo"].recall("deleting prod").rendered)

for key in names:
    as_[key].close()
for name in names.values():
    admin.remove_agent(name)
for a in admin.archives():
    if a.agent_a_name in names.values() or a.agent_b_name in names.values():
        admin.delete_archive(a.id)
admin.close()
print("\n(cleaned up the throwaway agents and their archives; the notes stay in memory)")
