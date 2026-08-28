"""Runbook check: the Agents-page hub contract (WP-D, items 4/8/15) and the 7c default.

  1. PATCH /api/agents/{name}: edit description/owns/workdir/model/colour; null clears;
     name and identity are refused; the operator record is refused
  2. remove with directory cleanup: uninstall first (courtyard pieces leave the files),
     then delete — the item-15 order
  3. Defaults: default_line_mode round trip (restored afterwards); a NEW line follows it

Safe against the dev hub: throwaway agents, a temp workdir, and the settings value is
put back exactly as found. Run against a hub started with `make run`:
    uv run python scripts/runbook/agents_edit.py
"""

import json
import os
import tempfile
import time
from pathlib import Path

from courtyard.common.client import HubClient, HubError

HUB = os.environ.get("COURTYARD_HUB_URL", "http://127.0.0.1:2626")


def hr(title):
    print("\n" + "=" * 78 + f"\n{title}\n" + "=" * 78)


admin = HubClient(HUB)
tag = str(time.time_ns())[-7:]
name = f"edit-rb-{tag}"
workdir = Path(tempfile.mkdtemp(prefix="courtyard-edit-rb-"))
agent, _ = admin.register_agent(name, "claude-code", "first draft", workdir=str(workdir))
print(f"registered throwaway {name} with workdir {workdir}")

hr("1. PATCH — edit, clear, and the refusals")
updated = admin._call(
    "PATCH", f"/api/agents/{name}", {"description": "edited", "model": "haiku", "color": "teal"}
)
print(
    f"edited        : description={updated['description']!r} model={updated['model']!r} color={updated['color']}"
)
updated = admin._call("PATCH", f"/api/agents/{name}", {"model": None})
print(f"null clears   : model={updated['model']}")
for label, target, patch in (
    ("name is identity", name, {"name": "impostor"}),
    ("operator locked", "operator", {"description": "x"}),
):
    try:
        admin._call("PATCH", f"/api/agents/{target}", patch)
        print(f"{label:14}: ACCEPTED — that is a bug")
    except HubError as exc:
        print(f"{label:14}: refused ({exc.code})")

hr("2. REMOVE WITH CLEANUP  (item 15: uninstall, then delete)")
admin._call("POST", f"/api/agents/{name}/install", {})
has_entry = "courtyard" in json.loads((workdir / ".mcp.json").read_text())["mcpServers"]
print(f"installed     : courtyard entry in .mcp.json = {has_entry}")
admin._call("POST", f"/api/agents/{name}/uninstall", {})
admin._call("DELETE", f"/api/agents/{name}")
left = json.loads((workdir / ".mcp.json").read_text()) if (workdir / ".mcp.json").exists() else {}
print(
    f"cleaned+gone  : entry left = {'courtyard' in (left.get('mcpServers') or {})}; "
    f"removed = {admin._call('GET', f'/api/agents/{name}')['removed_at'] is not None}"
)

hr("3. DEFAULTS  (7c: the dial a NEW line starts on)")
before = admin._call("GET", "/api/settings")["default_line_mode"]
try:
    admin._call("PATCH", "/api/settings", {"default_line_mode": "auto_pass"})
    a, _ = admin.register_agent(f"edit-rb-a-{tag}", "puppet")
    _, b_token = admin.register_agent(f"edit-rb-b-{tag}", "puppet")
    b = HubClient(HUB, f"edit-rb-b-{tag}", b_token)
    msg = b.send(a.name, "hello")
    print(f"new line under auto_pass default: message status = {msg.status} (queued = no gate)")
    b.close()
    for extra in (a.name, f"edit-rb-b-{tag}"):
        admin._call("DELETE", f"/api/agents/{extra}")
finally:
    admin._call("PATCH", "/api/settings", {"default_line_mode": before})
    print(f"default restored to {before!r}")

admin.close()
print("\n(cleaned up the throwaway agents; temp workdir left for inspection:", workdir, ")")
