"""Runbook check: stored agent tokens — readable again and rotatable (design D19).

  1. the token handed out at registration can be read back from the hub
  2. install needs no token passed in: the hub writes the stored one
  3. rotation: the old token is refused, the new one works, the running session is dropped
  4. re-installing writes the new token into .mcp.json

Run against a hub started with `make db-up && make run`:
    uv run python scripts/runbook/token_rotation.py

Throwaway: it registers one agent under a temp workdir and removes both at the end.
"""

import json
import shutil
import tempfile
import time
from pathlib import Path

from courtyard.common.client import HubClient, HubError

HUB = "http://127.0.0.1:2626"
DEAD_ENDPOINT = "http://127.0.0.1:9/"  # attach wants a local URL; nothing will be pushed here


def hr(title):
    print("\n" + "=" * 78 + f"\n{title}\n" + "=" * 78)


def mask(token):
    return token[:6] + "…" + token[-4:]


admin = HubClient(HUB)
name = f"rotate-{str(time.time_ns())[-7:]}"
workdir = Path(tempfile.mkdtemp(prefix="courtyard-rb-"))
mcp = workdir / ".mcp.json"


def token_in_file():
    return json.loads(mcp.read_text())["mcpServers"]["courtyard"]["env"]["COURTYARD_TOKEN"]


_agent, token = admin.register_agent(name, "claude-code", "runbook agent", None, str(workdir))
print(f"registered {name}; token at registration: {mask(token)}")

hr("1. READ IT BACK  (GET /api/agents/{name}/token)")
stored = admin.token_of(name)
print(f"stored token : {mask(stored)}   <- same as at registration? {stored == token}")

hr("2. INSTALL WITHOUT PASSING A TOKEN  (the hub writes the stored one)")
result = admin.install(name, workdir=str(workdir))
print(f"wrote        : {result['path']}")
print(
    f"token in file: {mask(token_in_file())}   <- equals the stored one? {token_in_file() == stored}"
)

hr("3. ROTATE  (POST /api/agents/{name}/token)")
as_agent = HubClient(HUB, name=name, token=token)
as_agent.attach(DEAD_ENDPOINT, "runbook-channel-token")
print(f"status before: {admin._call('GET', f'/api/agents/{name}')['status']}   <- attached")
rotated, new = admin.rotate_token(name)
print(f"new token    : {mask(new)}   <- different from the old one? {new != token}")
print(f"status after : {rotated.status}   <- its session can no longer reach the hub")
try:
    as_agent.inbox()
    print("old token    : STILL ACCEPTED — that is a bug")
except HubError as exc:
    print(f"old token    : refused ({exc})")
print(f"new token    : inbox read OK -> {HubClient(HUB, name=name, token=new).inbox()}")
print(f"read back    : {mask(admin.token_of(name))}   <- the new one")

hr("4. RE-INSTALL  (writes the new token)")
again = admin.install(name, workdir=str(workdir))
print(f"replaced the courtyard entry: {again['replaced_server']}")
print(f"token in file now equals the new token: {token_in_file() == new}")

admin.uninstall(name, str(workdir))
admin._call("DELETE", f"/api/agents/{name}")
as_agent.close()
admin.close()
shutil.rmtree(workdir, ignore_errors=True)
print("\n(cleaned up the throwaway agent and temp workdir.)")
