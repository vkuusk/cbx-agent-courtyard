"""Writing an agent's launch config into its project (design §8/D8, step 6d; WP-A).

The operator never hand-edits `.mcp.json`: the hub renders the courtyard MCP-server block
and merges it into the agent's project file, backing up whatever was already there so the
step is reversible. Other MCP servers and other top-level keys in the file are preserved.

Install also writes `<workdir>/.claude/settings.local.json` (WP-A, decision D21) — still
configuration, not behaviour (no hooks, D14): a permission rule pre-approving the
courtyard MCP tools (without it Claude Code stops the agent's every `courtyard_send`
with a terminal prompt, feedback 7.2), the agent's declared model (feedback 1), and a
status line naming the agent (feedback 2) — the status line only when the agent has
none, never clobbering an existing one. The file is per-machine and carries no secret;
Claude Code adds it to git excludes when it writes it itself, and the merge here
preserves whatever else it holds. The one-time trust dialog for a project's `.mcp.json`
servers cannot be pre-approved — that stays.

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
from courtyard.hub.core.shift import launch_command_text

MCP_FILENAME = ".mcp.json"
BACKUP_SUFFIX = ".courtyard-bak"
SERVER_KEY = "courtyard"
SETTINGS_DIR = ".claude"
SETTINGS_FILENAME = "settings.local.json"
# Item 35: the human-facing wrapper — nobody should have to remember the channel flag.
SCRIPT_FILENAME = "start-with-courtyard.sh"
SCRIPT_MARK = "Written by the courtyard"  # first comment line; uninstall keys on it
ALLOW_RULE = f"mcp__{SERVER_KEY}"  # pre-approves every courtyard tool (docs-verified form)
STATUS_MARK = "· courtyard'"  # a status-line command ending like this is ours (uninstall)

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


def start_script(agent_name: str, model: str | None) -> str:
    """Item 35: `start-with-courtyard.sh` — the one thing a human is told to run when
    starting an agent by hand. Carries the channel flag (whose absence is exactly the
    deaf-session failure of items 30/33) and the agent's model; regenerated on every
    install, so a model change or a flag-contract drift follows a re-register."""
    return (
        "#!/bin/sh\n"
        f"# {SCRIPT_MARK} for agent '{agent_name}'. Starts this agent's Claude Code\n"
        "# session connected to the courtyard hub (the channel flag included).\n"
        "# Regenerated on every install; extra arguments are passed through to claude.\n"
        f'cd "$(dirname "$0")" && exec {launch_command_text(model)} "$@"\n'
    )


def status_line(agent_name: str) -> dict:
    """A status line that answers "which agent is this terminal?" (feedback item 2)."""
    return {"type": "command", "command": f"echo '⏺ {agent_name} · courtyard'", "padding": 0}


def merge_settings(existing: dict | None, agent_name: str, model: str | None) -> dict:
    """The agent-side profile merged over `.claude/settings.local.json` (WP-A, D21).

    The allow rule is appended if missing; the model is the operator's declared intent and
    wins when set (untouched when the agent has none); the status line is set when the
    file has none — or when the existing one is recognisably OURS (`STATUS_MARK`), so a
    workdir re-registered under a new name stops announcing the old one (feedback item
    19). A status line somebody wrote themselves is never clobbered.
    """
    doc = dict(existing) if existing else {}
    permissions = dict(doc.get("permissions") or {})
    allow = list(permissions.get("allow") or [])
    if ALLOW_RULE not in allow:
        allow.append(ALLOW_RULE)
    permissions["allow"] = allow
    doc["permissions"] = permissions
    if model:
        doc["model"] = model
    current = doc.get("statusLine")
    ours = isinstance(current, dict) and str(current.get("command", "")).endswith(STATUS_MARK)
    if "statusLine" not in doc or ours:
        doc["statusLine"] = status_line(agent_name)
    return doc


@dataclass(frozen=True)
class InstallResult:
    path: str
    backed_up: str | None  # backup path, if an existing file was overwritten
    replaced_server: bool  # a previous `courtyard` server entry was replaced
    settings_path: str  # `.claude/settings.local.json` — allow rule, model, status line
    settings_backed_up: str | None
    script_path: str  # `start-with-courtyard.sh` — the human launch wrapper (item 35)
    script_backed_up: str | None  # only a file that was NOT ours gets backed up
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


def install(
    workdir: str,
    command: str,
    hub_url: str,
    agent_name: str,
    token: str,
    model: str | None = None,
) -> InstallResult:
    """Merge the courtyard server into `<workdir>/.mcp.json` (0600, with a backup) and the
    agent-side profile into `<workdir>/.claude/settings.local.json` (WP-A)."""
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

    settings_dir = directory / SETTINGS_DIR
    settings_target = settings_dir / SETTINGS_FILENAME
    s_existing, s_raw = _read_existing(settings_target)
    settings_backed_up: str | None = None
    if s_raw is not None:
        s_backup = settings_dir / (SETTINGS_FILENAME + BACKUP_SUFFIX)
        s_backup.write_text(s_raw)
        settings_backed_up = str(s_backup)
    settings_dir.mkdir(exist_ok=True)
    settings_doc = merge_settings(s_existing, agent_name, model)
    settings_target.write_text(json.dumps(settings_doc, indent=2) + "\n")

    # Item 35: the launch wrapper. Ours is regenerated in place; a file of this name
    # that is NOT ours is backed up first — and never rotated away by re-installs,
    # unlike the json backups (their flaw is recorded in feedback item 28).
    script_target = directory / SCRIPT_FILENAME
    script_backed_up: str | None = None
    if script_target.exists() and SCRIPT_MARK not in script_target.read_text():
        script_backup = directory / (SCRIPT_FILENAME + BACKUP_SUFFIX)
        script_backup.write_text(script_target.read_text())
        script_backed_up = str(script_backup)
    script_target.write_text(start_script(agent_name, model))
    os.chmod(script_target, 0o755)

    return InstallResult(
        str(target),
        backed_up,
        replaced,
        str(settings_target),
        settings_backed_up,
        str(script_target),
        script_backed_up,
        WARNING,
    )


@dataclass(frozen=True)
class UninstallResult:
    path: str
    restored_from_backup: bool  # the pre-install file was put back verbatim
    removed_server: bool  # our server key was dropped from a file we did not back up
    settings_restored: bool  # settings.local.json put back from its backup
    settings_cleaned: bool  # our allow rule / status line removed from it
    script_restored: bool  # start-with-courtyard.sh put back from its backup
    script_removed: bool  # our wrapper script deleted (a foreign one is never touched)


def _uninstall_settings(directory: Path) -> tuple[bool, bool]:
    """Reverse the settings side: restore the backup, else remove exactly what install
    adds — the allow rule, and the status line only if it is ours (`STATUS_MARK`). The
    model is left as-is: it may have been retuned by hand and carries no courtyard
    marker to recognise. Returns (restored, cleaned)."""
    settings_dir = directory / SETTINGS_DIR
    target = settings_dir / SETTINGS_FILENAME
    backup = settings_dir / (SETTINGS_FILENAME + BACKUP_SUFFIX)
    if backup.exists():
        target.write_text(backup.read_text())
        backup.unlink()
        return True, False
    existing, _ = _read_existing(target)
    if not existing:
        return False, False
    cleaned = False
    permissions = existing.get("permissions") or {}
    allow = permissions.get("allow") or []
    if ALLOW_RULE in allow:
        cleaned = True
        allow = [rule for rule in allow if rule != ALLOW_RULE]
        if allow:
            permissions["allow"] = allow
        else:
            permissions.pop("allow", None)
        if permissions:
            existing["permissions"] = permissions
        else:
            existing.pop("permissions", None)
    sl = existing.get("statusLine")
    if isinstance(sl, dict) and str(sl.get("command", "")).endswith(STATUS_MARK):
        existing.pop("statusLine")
        cleaned = True
    if cleaned:
        if existing:
            target.write_text(json.dumps(existing, indent=2) + "\n")
        else:
            # We created the file (it held only our profile). Remove it, not leave `{}`.
            target.unlink()
    return False, cleaned


def _uninstall_script(directory: Path) -> tuple[bool, bool]:
    """Reverse the wrapper: restore a backed-up foreign script, else delete the file
    only when it is recognisably ours (`SCRIPT_MARK`). Returns (restored, removed)."""
    target = directory / SCRIPT_FILENAME
    backup = directory / (SCRIPT_FILENAME + BACKUP_SUFFIX)
    if backup.exists():
        target.write_text(backup.read_text())
        os.chmod(target, 0o755)
        backup.unlink()
        return True, False
    if target.exists() and SCRIPT_MARK in target.read_text():
        target.unlink()
        return False, True
    return False, False


def uninstall(workdir: str) -> UninstallResult:
    """Reverse an install: restore the backups if present, else drop just what we added."""
    directory = Path(workdir).expanduser()
    target = directory / MCP_FILENAME
    backup = directory / (MCP_FILENAME + BACKUP_SUFFIX)
    settings_restored, settings_cleaned = _uninstall_settings(directory)
    script_restored, script_removed = _uninstall_script(directory)
    side_effects = settings_restored or settings_cleaned or script_restored or script_removed

    if backup.exists():
        target.write_text(backup.read_text())
        os.chmod(target, 0o600)
        backup.unlink()
        return UninstallResult(
            str(target),
            restored_from_backup=True,
            removed_server=False,
            settings_restored=settings_restored,
            settings_cleaned=settings_cleaned,
            script_restored=script_restored,
            script_removed=script_removed,
        )

    existing, _ = _read_existing(target)
    servers = (existing or {}).get("mcpServers") or {}
    if SERVER_KEY not in servers:
        if side_effects:
            return UninstallResult(
                str(target),
                restored_from_backup=False,
                removed_server=False,
                settings_restored=settings_restored,
                settings_cleaned=settings_cleaned,
                script_restored=script_restored,
                script_removed=script_removed,
            )
        raise NothingToUninstall(f"no courtyard entry and no backup at {target} — nothing to undo.")
    del servers[SERVER_KEY]
    if servers:
        existing["mcpServers"] = servers
        target.write_text(json.dumps(existing, indent=2) + "\n")
    else:
        # We created the file (it held only our server). Remove it rather than leave `{}`.
        target.unlink()
    return UninstallResult(
        str(target),
        restored_from_backup=False,
        removed_server=True,
        settings_restored=settings_restored,
        settings_cleaned=settings_cleaned,
        script_restored=script_restored,
        script_removed=script_removed,
    )
