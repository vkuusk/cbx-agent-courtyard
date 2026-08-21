"""Runbook check: the hub writes an agent's .mcp.json into its workdir (design §8/D8, 6d).

Proves the 6d install path without a Claude Code session:
  1. a project that already has another MCP server keeps it, and the original is backed up
  2. the courtyard block is written with the token inline, and the file is chmod 600
  3. uninstall restores the project's original .mcp.json exactly

Run against a hub started with `make db-up && make run`:
    uv run python scripts/runbook/install_mcp_json.py

Throwaway: it registers one agent under a temp workdir and removes both at the end.
"""

import json
import os
import shutil
import stat
import tempfile
import time
from pathlib import Path

from courtyard.common.client import HubClient

HUB = "http://127.0.0.1:2626"


def hr(title):
    print("\n" + "=" * 78 + f"\n{title}\n" + "=" * 78)


admin = HubClient(HUB)
# Unique per run: agent names are permanent (removed names stay reserved), so a coarse
# suffix would clash on a fast re-run.
name = f"coding-{str(time.time_ns())[-7:]}"
workdir = Path(tempfile.mkdtemp(prefix="courtyard-rb-"))

# The project already has its own MCP server — install must not clobber it.
mcp = workdir / ".mcp.json"
mcp.write_text(json.dumps({"mcpServers": {"my-linter": {"command": "run-linter"}}}, indent=2))
print(f"workdir: {workdir}")
print(f"pre-existing .mcp.json servers: {list(json.loads(mcp.read_text())['mcpServers'])}")

_agent, token = admin.register_agent(name, "claude-code", "writes payments", "the payments service")

hr("1. INSTALL  (hub merges the courtyard block into the agent's workdir)")
result = admin.install(name, token, str(workdir))
print(f"wrote      : {result['path']}")
print(f"backed up  : {result['backed_up']}")
print(f"warning    : {result['warning']}")

doc = json.loads(mcp.read_text())
print(f"\nservers now: {list(doc['mcpServers'])}   <- my-linter kept, courtyard added")
env = doc["mcpServers"]["courtyard"]["env"]
masked = env["COURTYARD_TOKEN"][:6] + "…"
print(f"courtyard env: AGENT_NAME={env['COURTYARD_AGENT_NAME']} TOKEN={masked} (inline)")
print(f"file mode  : {oct(stat.S_IMODE(os.stat(mcp).st_mode))}   <- 0o600")
print(f"backup has : {list(json.loads(Path(result['backed_up']).read_text())['mcpServers'])}")

hr("2. UNINSTALL  (restore the project's original file)")
undo = admin.uninstall(name, str(workdir))
print(f"restored from backup: {undo['restored_from_backup']}")
print(
    f"servers now : {list(json.loads(mcp.read_text())['mcpServers'])}   <- back to just my-linter"
)
print(f"backup gone : {not Path(result['backed_up']).exists()}")

admin._call("DELETE", f"/api/agents/{name}")
shutil.rmtree(workdir, ignore_errors=True)
print("\n(cleaned up the throwaway agent and temp workdir.)")
