"""Terminal spawners for the shift (design §8.1, D23).

Fire-and-forget by principle (§8): spawn opens a terminal window running the agent's
launch command and returns an opaque window reference — the one thing the hub records,
so End shift can close exactly what it opened. The hub never supervises the process;
liveness stays the only health signal.

Closing: terminal apps confirm before closing a window with a running process, which
would turn End shift into a dialog per agent. So close() first ends the processes on the
window's tty (SIGTERM to the process group leaders), then closes the now-quiet window.
"""

from __future__ import annotations

import json
import logging
import shlex
import subprocess
import time
from typing import Protocol

logger = logging.getLogger("courtyard.hub")

OSASCRIPT_TIMEOUT = 15.0

TERMINAL_APPS = ("Terminal", "iTerm2")


class SpawnFailed(Exception):
    """The terminal app refused or osascript errored; the caller logs and moves on."""


class TerminalSpawner(Protocol):
    def spawn(self, cwd: str, command: str) -> str | None:
        """Open a terminal window running `cd <cwd> && <command>`; returns the window
        reference for close(), or None when the reference could not be captured."""
        ...

    def close(self, ref: str) -> bool:
        """Close the window spawn() opened. Best-effort; False when it was already gone."""
        ...

    def alive(self, ref: str) -> bool:
        """Is the spawned window's session still running? (D25: resume respawns only the
        dead ones — a window merely waiting on a first-run dialog must not be doubled.)"""
        ...


def applescript_str(value: str) -> str:
    """A double-quoted AppleScript string literal. The values come from the operator's
    own registry (D3), but a workdir with a quote or backslash must not break the script."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def shell_command(cwd: str, command: str) -> str:
    return f"cd {shlex.quote(cwd)} && {command}"


def _osascript(script: str) -> str:
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        timeout=OSASCRIPT_TIMEOUT,
        check=False,  # the caller inspects returncode
    )
    if result.returncode != 0:
        raise SpawnFailed(result.stderr.strip() or f"osascript exited {result.returncode}")
    return result.stdout.strip()


def _tty_busy(name: str) -> bool:
    return (
        subprocess.run(
            ["pgrep", "-t", name], capture_output=True, timeout=10, check=False
        ).returncode
        == 0
    )


def _ref_alive(ref: str) -> bool:
    """Shared by both macOS spawners: the session lives iff its tty has processes.
    A ref without a tty cannot be verified and reads as dead (resume will respawn)."""
    try:
        info = json.loads(ref)
    except (TypeError, ValueError):
        return False
    tty = info.get("tty") or ""
    return bool(tty) and _tty_busy(tty.removeprefix("/dev/"))


def _kill_tty(tty: str) -> None:
    """End everything on the window's tty and WAIT until it is actually gone, so the
    close that follows finds no running process (and therefore shows no confirmation
    dialog). Found live (WP-F check, 2026-08-26): closing immediately after SIGTERM races
    the process's shutdown — the slower window pops Terminal's "process is running" modal
    and stays open. TERM first, escalate to KILL if the tty is still busy."""
    name = tty.removeprefix("/dev/")
    for signal, wait in (("-TERM", 5.0), ("-KILL", 2.0)):
        subprocess.run(["pkill", signal, "-t", name], capture_output=True, timeout=10, check=False)
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            if not _tty_busy(name):
                return
            time.sleep(0.2)
    logger.warning("tty %s still busy after TERM and KILL", name)


class AppleTerminal:
    """Terminal.app via osascript. The reference is the window id + the tab's tty."""

    def spawn(self, cwd: str, command: str) -> str | None:
        line = applescript_str(shell_command(cwd, command))
        out = _osascript(
            'tell application "Terminal"\n'
            f"  set t to do script {line}\n"
            # the tab's own window, not "front window" — spawning several agents
            # back-to-back must never record a neighbour's id
            "  set w to id of (first window whose selected tab is t)\n"
            "  set y to tty of t\n"
            "  activate\n"
            "end tell\n"
            'return (w as text) & "|" & y'
        )
        window_id, _, tty = out.partition("|")
        return json.dumps({"app": "Terminal", "window_id": window_id, "tty": tty})

    def alive(self, ref: str) -> bool:
        return _ref_alive(ref)

    def close(self, ref: str) -> bool:
        info = json.loads(ref)
        if info.get("tty"):
            _kill_tty(info["tty"])
        try:
            out = _osascript(
                'tell application "Terminal"\n'
                f"  set targets to every window whose id is {int(info['window_id'])}\n"
                "  repeat with w in targets\n"
                "    close w\n"
                "  end repeat\n"
                "  return (count of targets) as text\n"
                "end tell"
            )
        except (SpawnFailed, subprocess.TimeoutExpired) as exc:
            logger.warning("closing Terminal window %s failed: %s", info.get("window_id"), exc)
            return False
        return out != "0"


class ITerm2:
    """iTerm2 via osascript. The reference is the window id + the session's tty."""

    def spawn(self, cwd: str, command: str) -> str | None:
        line = applescript_str(shell_command(cwd, command))
        out = _osascript(
            'tell application "iTerm2"\n'
            "  set w to (create window with default profile)\n"
            "  tell current session of w\n"
            f"    write text {line}\n"
            "    set y to tty\n"
            "  end tell\n"
            "  activate\n"
            "end tell\n"
            'return (id of w as text) & "|" & y'
        )
        window_id, _, tty = out.partition("|")
        return json.dumps({"app": "iTerm2", "window_id": window_id, "tty": tty})

    def alive(self, ref: str) -> bool:
        return _ref_alive(ref)

    def close(self, ref: str) -> bool:
        info = json.loads(ref)
        if info.get("tty"):
            _kill_tty(info["tty"])
        try:
            _osascript(
                'tell application "iTerm2"\n'
                "  repeat with w in windows\n"
                f"    if (id of w as text) is {applescript_str(str(info['window_id']))} then close w\n"
                "  end repeat\n"
                "end tell"
            )
        except (SpawnFailed, subprocess.TimeoutExpired) as exc:
            logger.warning("closing iTerm2 window %s failed: %s", info.get("window_id"), exc)
            return False
        return True


def render_template(template: str, cwd: str, command: str) -> str:
    """Fill a custom terminal's start string: `{dir}` and `{command}` become the
    shell-quoted workdir and launch command."""
    return template.replace("{dir}", shlex.quote(cwd)).replace(
        "{command}", shlex.quote(shell_command(cwd, command))
    )


class CommandTemplate:
    """An operator-defined terminal application (Admin → Terminal application): its
    start string is a shell template run fire-and-forget. Honest limits, stated in the
    UI too: we get no window handle back from an arbitrary launcher, so End shift cannot
    close what it opened (ref None) and resume treats its windows as unverifiable."""

    def __init__(self, template: str):
        self._template = template

    def spawn(self, cwd: str, command: str) -> str | None:
        rendered = render_template(self._template, cwd, command)
        # shell=True on purpose: this IS the operator's own start string (D3 trust model)
        subprocess.Popen(rendered, shell=True, start_new_session=True)
        return None

    def close(self, ref: str) -> bool:
        return False

    def alive(self, ref: str) -> bool:
        return False


def make_spawner(terminal_app: str, custom: dict[str, str] | None = None) -> TerminalSpawner:
    if terminal_app == "iTerm2":
        return ITerm2()
    if custom and terminal_app in custom:
        return CommandTemplate(custom[terminal_app])
    return AppleTerminal()
