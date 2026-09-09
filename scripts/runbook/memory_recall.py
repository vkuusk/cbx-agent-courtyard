"""Runbook check: hub memory, slice 1 — the case file and recall (design hub-memory.md).

  1. two agents settle an ask on a supervised line (one draft returned with a comment,
     the answer approved), the asker closes the thread -> ONE case file appears, with
     the ask, the resolution that got through, the verdicts, the counts
  2. a third agent recalls with a question -> the hub's rendered listing, trimmed and
     bounded, ranked with the participants' declared domains
  3. the third agent fetches the case file in full by its handle
  4. nothing matching is said plainly; an expired thread leaves no case file

Run against a hub started with `make run` (or pass --hub / COURTYARD_HUB_URL):
    uv run python scripts/runbook/memory_recall.py

Throwaway: three time-suffixed agents, linked so it works under discovery `manual`
too; all three are removed at the end, with the archives and case files they leave.
Nothing courtyard-wide is changed.
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
admin.link(names["infra"], names["tf"])  # explicit so the check runs under manual discovery too
print(f"registered {', '.join(names.values())} (dummies, linked infra-tf)")


def approve_all(note=None):
    for m in admin.pending():
        if m.sender_name in names.values():
            admin.decide(m.id, "approve", note)


hr("1. AN EXCHANGE SETTLES, THE THREAD CLOSES  -> one case file")
q = as_["infra"].send(names["tf"], "does the vpc module support ipv6?", new_thread=True)
approve_all()
as_["tf"].inbox()
draft = as_["tf"].send(names["infra"], "no idea")
admin.decide(draft.id, "return", "look it up in the module before answering")
as_["tf"].inbox()
answer = as_["tf"].send(names["infra"], "yes since v3; set enable_ipv6 = true")
admin.decide(answer.id, "approve", "fine")
as_["infra"].inbox()
before = {r.id for r in admin.memory(participant=names["infra"])}
as_["infra"].close_thread(names["tf"])
records = [r for r in admin.memory(participant=names["infra"]) if r.id not in before]
print(f"case files written by the close: {len(records)}   (expected 1)")
(case,) = records
print(f"participants : {' / '.join(f'{p.name} ({p.sme_domain})' for p in case.participants)}")
print(f"ask          : {case.ask!r}")
print(f"resolution   : {case.resolution!r}   <- the answer that got through, not the draft")
print(f"verdicts     : {case.verdicts}")
print(
    f"counts       : {case.message_count} messages, {case.approved} approved, "
    f"{case.returned} returned, {case.dropped} dropped"
)

hr("2. A THIRD AGENT RECALLS  (what its courtyard_recall tool prints)")
view = as_["argo"].recall("ipv6 terraform module")
print(view.rendered)
print(f"\nrecords returned: {len(view.records)} (bounded by Admin -> Recall returns)")
hit = view.records[0] if view.records else None
print(f"our case first : {hit is not None and hit.id == case.id}")

hr("3. THE FULL CASE FILE BY ITS HANDLE")
full = as_["argo"].recall_case(case.id)
print(full.rendered)

hr("4. NOTHING FOUND; AN EXPIRED THREAD LEAVES NOTHING")
print(as_["argo"].recall("kubernetes ingress").rendered)
opened = as_["infra"].send(names["tf"], "left open on purpose", new_thread=True)
approve_all()
count_before = len(admin.memory(participant=names["infra"]))
print(f"\nopen thread on the line: {opened.thread_id}; case files now: {count_before}")
print("(End shift would expire it; only a CLOSED thread ever becomes a case file)")

for key in names:
    as_[key].close()
for name in names.values():
    admin.remove_agent(name)
for a in admin.archives():
    if a.agent_a_name in names.values() or a.agent_b_name in names.values():
        admin.delete_archive(a.id)
admin.close()
print("\n(cleaned up the throwaway agents and their archives; case files stay with the memory)")
