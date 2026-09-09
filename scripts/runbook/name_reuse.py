"""Runbook check: a removed agent's name can be registered again (design §5.1, D36).

  1. an agent with history is removed: its token is refused, its line is archived
  2. the same name is registered again, as a different type: the hub revives the
     agent's own row (same id) with a new token, fresh liveness and the new fields
  3. the old token stays dead, the new one works, and a live name is still refused
  4. the first life's archive still names the agent; no line came back with it

Run against a hub started with `make run`:
    uv run python scripts/runbook/name_reuse.py

Throwaway: two agents with time-suffixed names, both removed at the end (the archive
they leave behind is deleted too).
"""

import time

from courtyard.common.client import HubClient, HubError

HUB = "http://127.0.0.1:2626"
DEAD_ENDPOINT = "http://127.0.0.1:9/"  # attach wants a local URL; nothing is pushed here


def hr(title):
    print("\n" + "=" * 78 + f"\n{title}\n" + "=" * 78)


def mask(token):
    return token[:6] + "…" + token[-4:]


admin = HubClient(HUB)
suffix = str(time.time_ns())[-7:]
name, peer = f"phoenix-{suffix}", f"peer-{suffix}"

first, old_token = admin.register_agent(name, "dummy", "first life")
_, peer_token = admin.register_agent(peer, "dummy", "the peer")
as_peer = HubClient(HUB, name=peer, token=peer_token)
admin.link(peer, name)  # works under discovery manual too; under auto it is the same line
as_peer.send(name, "hello, first life")  # gives the pair a line with history
print(f"registered {name} (id {first.id}, type dummy); token {mask(old_token)}")
print(f"the peer {peer} sent it a message: one line, one message")

hr("1. REMOVE  (DELETE /api/agents/{name})")
removed = admin.remove_agent(name)
print(f"status        : {removed.status}, removed_at set: {removed.removed_at is not None}")
try:
    HubClient(HUB, name=name, token=old_token).inbox()
    print("old token     : STILL ACCEPTED — that is a bug")
except HubError as exc:
    print(f"old token     : refused ({exc.code})")
archives = [a for a in admin.archives() if name in (a.agent_a_name, a.agent_b_name)]
print(f"archived lines: {len(archives)} (reason {archives[0].reason if archives else '-'})")

hr("2. REGISTER THE SAME NAME AGAIN  (POST /api/agents, type claude-code this time)")
second, new_token = admin.register_agent(name, "claude-code", "second life", model="sonnet")
print(f"same id       : {second.id == first.id}   <- the row is revived, not replaced")
print(f"type          : {second.type}, description: {second.description!r}, model: {second.model}")
print(f"status        : {second.status}, removed_at cleared: {second.removed_at is None}")
print(
    f"new token     : {mask(new_token)}   <- different from the old one? {new_token != old_token}"
)

hr("3. TOKENS AND THE NAME")
try:
    HubClient(HUB, name=name, token=old_token).inbox()
    print("old token     : STILL ACCEPTED — that is a bug")
except HubError as exc:
    print(f"old token     : still refused ({exc.code})")
as_agent = HubClient(HUB, name=name, token=new_token)
print(f"new token     : inbox read OK -> {as_agent.inbox()}")
try:
    admin.register_agent(name, "dummy")
    print("live name     : REGISTERED TWICE — that is a bug")
except HubError as exc:
    print(f"live name     : refused ({exc.code})   <- only a removed name is free")

hr("4. THE FIRST LIFE'S HISTORY")
archives = [a for a in admin.archives() if name in (a.agent_a_name, a.agent_b_name)]
print(f"archive still names {name}: {bool(archives)} ({len(archives)} archive)")
lines = [ln for ln in admin.lines() if second.id in (ln.agent_a, ln.agent_b)]
print(f"lines on the revived agent: {len(lines)}   <- nothing resurrected; history stays archived")

for a in archives:
    admin.delete_archive(a.id)
admin.remove_agent(name)
admin.remove_agent(peer)
for a in admin.archives():
    if name in (a.agent_a_name, a.agent_b_name) or peer in (a.agent_a_name, a.agent_b_name):
        admin.delete_archive(a.id)
as_agent.close()
as_peer.close()
admin.close()
print("\n(cleaned up both throwaway agents and their archives.)")
