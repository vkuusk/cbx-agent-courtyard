"""Runbook check: hub memory, slice 3 — similarity search (design hub-memory.md section 7).

Needs a hub whose COURTYARD_EMBEDDINGS_URL points at a real local encoder, e.g. Ollama:

    ollama pull nomic-embed-text
    COURTYARD_EMBEDDINGS_URL=http://127.0.0.1:11434/v1/embeddings make run

  1. the encoder status: which model, how many records carry its vector
  2. two case files settle; one embedding pass gives both a vector
  3. a PARAPHRASED question that shares no word with the record: full text misses,
     similarity finds it, and hybrid (the default, what courtyard_recall uses) too
  4. a question where the words agree: hybrid keeps the same answer first

Run against a hub started with `make run` (or pass --hub / COURTYARD_HUB_URL):
    uv run python scripts/runbook/memory_vectors.py

Exit 2 (skipped) when the hub has no encoder. Throwaway: three time-suffixed dummies,
linked so the check runs under discovery `manual` too; removed at the end with their
archives. The case files stay in memory.
"""

import argparse
import os
import sys
import time

from courtyard.common.client import HubClient

parser = argparse.ArgumentParser()
parser.add_argument("--hub", default=os.environ.get("COURTYARD_HUB_URL", "http://127.0.0.1:2626"))
HUB = parser.parse_args().hub


def hr(title):
    print("\n" + "=" * 78 + f"\n{title}\n" + "=" * 78)


admin = HubClient(HUB)

hr("1. THE ENCODER  (GET /api/memory/encoder)")
status = admin.memory_encoder()
for key in ("encoder", "model", "default_mode", "total", "embedded", "pending"):
    print(f"{key:<13}: {status[key]}")
if status["encoder"] == "none":
    print("\nSKIPPED: this hub has no encoder. Start one with COURTYARD_EMBEDDINGS_URL set")
    print("(see the header of this script), then run again.")
    admin.close()
    sys.exit(2)

suffix = str(time.time_ns())[-7:]
names = {"infra": f"infra-{suffix}", "db": f"db-{suffix}", "argo": f"argo-{suffix}"}
tokens = {}
for key, domain in (("infra", "the AWS estate"), ("db", "postgres databases"), ("argo", "argocd")):
    _, tokens[key] = admin.register_agent(names[key], "dummy", f"runbook {key}", domain)
as_ = {key: HubClient(HUB, name=names[key], token=tokens[key]) for key in names}
admin.link(names["infra"], names["db"])
admin.link(names["infra"], names["argo"])


def approve_all():
    for m in admin.pending():
        if m.sender_name in names.values():
            admin.decide(m.id, "approve")


def settle(asker, answerer, ask, answer):
    as_[asker].send(names[answerer], ask, new_thread=True)
    approve_all()
    as_[answerer].inbox()
    as_[answerer].send(names[asker], answer)
    approve_all()
    as_[asker].inbox()
    before = {r.id for r in admin.memory(participant=names[asker])}
    as_[asker].close_thread(names[answerer])
    (case,) = [r for r in admin.memory(participant=names[asker]) if r.id not in before]
    return case


hr("2. TWO CASE FILES SETTLE, ONE EMBEDDING PASS")
pg = settle(
    "infra", "db", "which postgres do we run?", "postgres 17 everywhere since the migration"
)
argo = settle(
    "infra", "argo", "how do we roll back a deploy?", "argocd app rollback to the previous sync"
)
print(f"case A: {pg.ask!r} -> {pg.resolution!r}")
print(f"case B: {argo.ask!r} -> {argo.resolution!r}")
embedded = admin.memory_embed()
print(f"embedding pass    : {embedded} record(s) got a vector from {status['model']}")
print(f"pending afterwards: {admin.memory_encoder()['pending']}")

hr("3. A PARAPHRASE THAT SHARES NO WORD WITH THE RECORD")
question = "what database release is in production"
exact = [r for r in admin.memory(question, mode="exact", participant=names["infra"])]
near = [r for r in admin.memory(question, mode="vector", participant=names["infra"])]
hybrid = [r for r in admin.memory(question, participant=names["infra"])]
print(f"question          : {question!r}")
print(
    f"full text         : {[r.resolution[:24] for r in exact]}   (expected: nothing, no word in common)"
)
print(f"similarity        : {[r.resolution[:24] for r in near]}   (expected: postgres first)")
print(f"hybrid (default)  : {[r.resolution[:24] for r in hybrid]}   (expected: postgres first)")
print(f"postgres first?   : {bool(hybrid) and hybrid[0].id == pg.id}")
print("\nwhat infra's courtyard_recall prints for it:")
print(as_["infra"].recall(question).rendered)

hr("4. WHERE THE WORDS AGREE, HYBRID AGREES")
question = "rollback a deploy"
hybrid = admin.memory(question, participant=names["infra"])
print(f"question          : {question!r}")
print(f"hybrid            : {[r.resolution[:24] for r in hybrid]}")
print(f"argocd first?     : {bool(hybrid) and hybrid[0].id == argo.id}")

for key in names:
    as_[key].close()
for name in names.values():
    admin.remove_agent(name)
for a in admin.archives():
    if a.agent_a_name in names.values() or a.agent_b_name in names.values():
        admin.delete_archive(a.id)
admin.close()
print("\n(cleaned up the throwaway agents and their archives; the case files stay in memory)")
