"""Writing an agent's launch config into its project (design §8/D8, step 6d).

The operator never hand-edits `.mcp.json`: the hub renders the courtyard MCP-server block
and merges it into the agent's project file, backing up whatever was already there so the
step is reversible. Other MCP servers and other top-level keys in the file are preserved.

**Dev-mode only.** The writer must share a filesystem with the agent's workdir; when the hub
runs in a container (live mode, 6f) the WebUI's copy-paste panel is the path instead.

**Token placement: inline + `chmod 600`** (architect's call, 2026-08-20). The file carries
the agent's bearer token in `env`, so it is written `0600` and must not be committed — the
returned `warning` says so, and the WebUI surfaces it. The other options considered
(`${VAR}` expansion, a separate token file) are recorded in the design doc; inline was chosen.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from courtyard.hub.core.errors import MalformedMcpJson, NothingToUninstall, WorkdirNotFound

MCP_FILENAME = ".mcp.json"
BACKUP_SUFFIX = ".courtyard-bak"
SERVER_KEY = "courtyard"

WARNING = (
    "This file now contains the agent's token and is set to chmod 600. Do NOT commit it — "
    "add .mcp.json to .gitignore if this directory is under version control."
)


def adapter_command() -> str:
    """Absolute path to the Claude Code adapter, for the launch config (D8/L0).

    Claude Code spawns MCP servers with the *agent's* project as cwd, so a relative command
    or a `uv run` would not resolve. The hub knows where its own venv is; the WebUI does not.
    """
    beside_hub = Path(sys.executable).parent / "courtyard-claude-mcp"
    if beside_hub.exists():
        return str(beside_hub)
    found = shutil.which("courtyard-claude-mcp")
    return found or f"{sys.executable} -m courtyard.adapters.claude_code.mcp_server"


def server_block(command: str, hub_url: str, agent_name: str, token: str) -> dict:
    """The `mcpServers.courtyard` entry — identical to the WebUI's copy-paste panel."""
    return {
        "command": command,
        "env": {
            "COURTYARD_HUB_URL": hub_url,
            "COURTYARD_AGENT_NAME": agent_name,
            "COURTYARD_TOKEN": token,
        },
    }


def merge(existing: dict | None, block: dict) -> dict:
    """Put our server under `mcpServers`, leaving every other server and key untouched."""
    doc = dict(existing) if existing else {}
    servers = dict(doc.get("mcpServers") or {})
    servers[SERVER_KEY] = block
    doc["mcpServers"] = servers
    return doc


@dataclass(frozen=True)
class InstallResult:
    path: str
    backed_up: str | None  # backup path, if an existing file was overwritten
    replaced_server: bool  # a previous `courtyard` server entry was replaced
    warning: str


def _read_existing(target: Path) -> tuple[dict | None, str | None]:
    """Return (parsed doc, raw text) for an existing `.mcp.json`, or (None, None)."""
    if not target.exists():
        return None, None
    raw = target.read_text()
    if not raw.strip():
        return None, raw
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MalformedMcpJson(
            f"{target} exists but is not valid JSON ({exc}); fix or move it, then retry — "
            "refusing to overwrite it blindly."
        ) from None
    if not isinstance(parsed, dict):
        raise MalformedMcpJson(f"{target} is valid JSON but not an object; refusing to merge.")
    return parsed, raw


def install(workdir: str, command: str, hub_url: str, agent_name: str, token: str) -> InstallResult:
    """Merge the courtyard server into `<workdir>/.mcp.json`, 0600, with a backup."""
    directory = Path(workdir).expanduser()
    if not directory.is_dir():
        raise WorkdirNotFound(
            f"workdir {workdir!r} is not a directory the hub can see. In dev mode this is the "
            "agent's project path; in live mode use the copy-paste config instead."
        )
    target = directory / MCP_FILENAME
    existing, raw = _read_existing(target)

    backed_up: str | None = None
    if raw is not None:
        backup = directory / (MCP_FILENAME + BACKUP_SUFFIX)
        backup.write_text(raw)
        backed_up = str(backup)

    replaced = bool(existing and SERVER_KEY in (existing.get("mcpServers") or {}))
    doc = merge(existing, server_block(command, hub_url, agent_name, token))
    target.write_text(json.dumps(doc, indent=2) + "\n")
    os.chmod(target, 0o600)
    return InstallResult(str(target), backed_up, replaced, WARNING)


@dataclass(frozen=True)
class UninstallResult:
    path: str
    restored_from_backup: bool  # the pre-install file was put back verbatim
    removed_server: bool  # our server key was dropped from a file we did not back up


def uninstall(workdir: str) -> UninstallResult:
    """Reverse an install: restore the backup if present, else drop just our server key."""
    directory = Path(workdir).expanduser()
    target = directory / MCP_FILENAME
    backup = directory / (MCP_FILENAME + BACKUP_SUFFIX)

    if backup.exists():
        target.write_text(backup.read_text())
        os.chmod(target, 0o600)
        backup.unlink()
        return UninstallResult(str(target), restored_from_backup=True, removed_server=False)

    existing, _ = _read_existing(target)
    servers = (existing or {}).get("mcpServers") or {}
    if SERVER_KEY not in servers:
        raise NothingToUninstall(f"no courtyard entry and no backup at {target} — nothing to undo.")
    del servers[SERVER_KEY]
    if servers:
        existing["mcpServers"] = servers
        target.write_text(json.dumps(existing, indent=2) + "\n")
    else:
        # We created the file (it held only our server). Remove it rather than leave `{}`.
        target.unlink()
    return UninstallResult(str(target), restored_from_backup=False, removed_server=True)
