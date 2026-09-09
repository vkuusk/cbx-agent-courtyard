"""Terminal spawners for the shift (design §8.1, D23).

Fire-and-forget by principle (§8): spawn opens a terminal window running the agent's
launch command and returns an opaque window reference — the one thing the hub records,
so End shift can close exactly what it opened. The hub never supervises the process;
liveness stays the only health signal.

Closing: terminal apps confirm before closing a window with a running process, which
would turn End shift into a dialog per agent. So close() first ends the processes on the
window's tty (SIGTERM to the process group leaders), then closes the now-quiet window.

Adding a terminal application the shift should fully drive (open AND close):

  1. subclass `OsascriptTerminal` below — `_open` is the app's AppleScript for opening a
     window on the agent's line and reporting the window id and the tty; the class
     attributes say how the app names itself and its windows
  2. register it in `BUILTIN_SPAWNERS`, and its name in `models.BUILTIN_TERMINALS` (the
     test suite refuses the two lists drifting apart); the WebUI reads the names from
     the hub
  3. run `scripts/runbook/terminal_spawners.py <name>` against the real app — the
     AppleScript is the part no unit test can see
"""

from __future__ import annotations

import json
import logging
import os
import shlex
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Protocol

logger = logging.getLogger("courtyard.hub")

OSASCRIPT_TIMEOUT = 15.0
TTY_REPORT_TIMEOUT = 5.0  # how long a spawned shell gets to report its own tty (Ghostty)


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


def _tty_pids(name: str) -> list[int]:
    """Every process whose controlling terminal is `name` (e.g. `ttys003`).

    `ps -t` and NOT `pgrep -t` (found live 2026-09-08, macOS 26 / Darwin 25.6): `pgrep -t`
    and `pkill -t` match nothing there for ANY tty, including the windows these spawners
    open themselves, while `ps -t` lists the processes correctly. On the pgrep pair,
    liveness read every window as dead (D25 asked its abandoned-shift question with the
    windows open, resume respawned live agents) and the pre-close kill was a silent
    no-op, so End shift closed windows and left the agents running."""
    result = subprocess.run(
        ["ps", "-t", name, "-o", "pid="],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,  # a tty that no longer exists is an error and means "nothing on it"
    )
    return [int(field) for field in result.stdout.split() if field.isdigit()]


def _tty_busy(name: str) -> bool:
    return bool(_tty_pids(name))


def _ref_alive(ref: str) -> bool:
    """Shared by every built-in spawner: the session lives iff its tty has processes.
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
    and stays open. TERM first, escalate to KILL if the tty is still busy.

    Signals go to the pids `ps -t` reports rather than through `pkill -t`; see
    `_tty_pids` for why the pgrep/pkill form cannot be trusted."""
    name = tty.removeprefix("/dev/")
    for sig, wait in ((signal.SIGTERM, 5.0), (signal.SIGKILL, 2.0)):
        for pid in _tty_pids(name):
            try:
                os.kill(pid, sig)
            except OSError as exc:  # already gone, or not ours to signal
                logger.debug("signalling pid %s on %s: %s", pid, name, exc)
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            if not _tty_busy(name):
                return
            time.sleep(0.2)
    logger.warning("tty %s still busy after TERM and KILL", name)


def _read_tty(path: str) -> str:
    """Wait for a spawned shell to write its tty into `path`. An empty answer is not
    fatal and is not fixable either: the window is open and the agent is running, but
    liveness cannot verify it and close cannot end it (as with a custom terminal)."""
    deadline = time.monotonic() + TTY_REPORT_TIMEOUT
    while time.monotonic() < deadline:
        try:
            reported = Path(path).read_text().strip()
        except OSError:
            reported = ""
        if reported:
            return reported
        time.sleep(0.1)
    logger.warning("spawned shell never reported its tty (%s)", path)
    return ""


class OsascriptTerminal:
    """A macOS terminal application driven through its AppleScript dictionary. The
    reference every subclass records has one shape, `{app, window_id, tty}`: the window
    id is what close() targets, the tty is what liveness and the pre-close kill use.

    What a subclass supplies: `_open` (the app's own way of opening a window on the
    agent's line and telling us the window id and the tty) and three class attributes
    describing how the app names itself and its windows. Everything else — the ref,
    liveness, and the close sequence — is the same for every app.

    The close sequence, in this order and for a reason each:

    1. count the windows with that id, BEFORE anything is killed: some apps (Ghostty
       always, Terminal.app under a "close the window when the shell exits" profile)
       retire the window the moment its shell ends, so a count taken after the kill can
       read zero for a close that worked. The count is the protocol's answer — False
       means the window was already gone before End shift got to it.
    2. end the processes on the window's tty and wait for them to go (`_kill_tty`): a
       window closing on a live process either orphans it or asks the operator first.
    3. close whatever the kill did not take with it.
    """

    name: str  # the BUILTIN_TERMINALS key; also the `app` field of the ref
    app: str  # how AppleScript addresses the app: `application "..."` or `application id "..."`
    text_ids = False  # window ids are integers unless the app's dictionary says text
    close_verb = "close w"  # the app's command for closing the window bound to `w`

    def spawn(self, cwd: str, command: str) -> str | None:
        window_id, tty = self._open(cwd, command)
        return json.dumps({"app": self.name, "window_id": window_id, "tty": tty})

    def alive(self, ref: str) -> bool:
        return _ref_alive(ref)

    def close(self, ref: str) -> bool:
        info = json.loads(ref)
        windows = f"(every window whose id is {self._id_literal(info['window_id'])})"
        try:
            found = _osascript(f"tell {self.app} to return (count of {windows}) as text") != "0"
            if info.get("tty"):
                _kill_tty(info["tty"])
            _osascript(
                f"tell {self.app}\n"
                f"  repeat with w in {windows}\n"
                f"    {self.close_verb}\n"
                "  end repeat\n"
                "end tell"
            )
        except (SpawnFailed, subprocess.TimeoutExpired) as exc:
            logger.warning("closing %s window %s failed: %s", self.name, info.get("window_id"), exc)
            return False
        return found

    def _id_literal(self, window_id: str) -> str:
        """The window id as the AppleScript literal a `whose id is` clause compares."""
        return applescript_str(str(window_id)) if self.text_ids else str(int(window_id))

    def _open(self, cwd: str, command: str) -> tuple[str, str]:
        """Open a window running the agent's line; return (window id, tty). The tty may
        be "" when the app cannot report it — recorded honestly, see `_read_tty`."""
        raise NotImplementedError


class AppleTerminal(OsascriptTerminal):
    """Terminal.app. `do script` runs the line in a new tab's login shell; the tab
    reports its tty and its window's id directly."""

    name = "Terminal"
    app = 'application "Terminal"'

    def _open(self, cwd: str, command: str) -> tuple[str, str]:
        line = applescript_str(shell_command(cwd, command))
        # Cold start (found live, 2026-08-28): when Terminal.app is not running, the
        # first `do script` launches it, and the app opens its own startup window — a
        # bare shell the hub never recorded, so End shift left it behind. So: check
        # `running` BEFORE the tell block (touching the app inside one launches it),
        # and on a cold start run the first agent in that startup window instead —
        # it becomes a normal recorded spawn. The fallback plain `do script` covers a
        # launch that opened no window; either way exactly one window per agent.
        out = _osascript(
            f"set wasRunning to {self.app} is running\n"
            f"tell {self.app}\n"
            "  if wasRunning then\n"
            f"    set t to do script {line}\n"
            "  else\n"
            "    launch\n"
            "    repeat 30 times\n"  # wait for the startup window (~3 s worst case)
            "      if (count of windows) > 0 then exit repeat\n"
            "      delay 0.1\n"
            "    end repeat\n"
            "    if (count of windows) > 0 then\n"
            f"      set t to do script {line} in window 1\n"
            "    else\n"
            f"      set t to do script {line}\n"
            "    end if\n"
            "  end if\n"
            # the tab's own window, not "front window" — spawning several agents
            # back-to-back must never record a neighbour's id
            "  set w to id of (first window whose selected tab is t)\n"
            "  set y to tty of t\n"
            "  activate\n"
            "end tell\n"
            'return (w as text) & "|" & y'
        )
        window_id, _, tty = out.partition("|")
        return window_id, tty


class ITerm2(OsascriptTerminal):
    """iTerm2. `write text` types the line into the new window's session, which reports
    its tty; the window id is an integer per iTerm2's dictionary."""

    name = "iTerm2"
    # iTerm2 ships as `iTerm.app` while calling itself iTerm2, and AppleScript resolves the
    # app by that filename: `tell application "iTerm2"` raises "Can't get application" and
    # the script then fails to even compile (found by the spawner runbook, 2026-09-08, on
    # iTerm2 3.6.6 — the whole iTerm2 spawner was dead). The bundle id is unambiguous.
    app = 'application id "com.googlecode.iterm2"'

    def _open(self, cwd: str, command: str) -> tuple[str, str]:
        line = applescript_str(shell_command(cwd, command))
        out = _osascript(
            f"tell {self.app}\n"
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
        return window_id, tty


class Ghostty(OsascriptTerminal):
    """Ghostty . The line is typed as the new surface's `initial input`, into a login
    shell that outlives the agent; the dictionary exposes no tty, so the shell reports
    its own through a temp file (`_read_tty`). Window ids are text.
    """

    name = "Ghostty"
    app = 'application "Ghostty"'
    text_ids = True  # "Stable ID for this window", type text
    close_verb = "close window w"  # `close` alone is the terminal-surface command

    def _open(self, cwd: str, command: str) -> tuple[str, str]:
        handle, ttyfile = tempfile.mkstemp(prefix="courtyard-tty-")
        os.close(handle)
        try:
            typed = f"tty > {shlex.quote(ttyfile)}; {shell_command(cwd, command)}"
            # AppleScript string literals hold no newline, and the line only runs once
            # the shell reads a return: `& linefeed` supplies it.
            window_id = _osascript(
                f"tell {self.app}\n"
                "  set cfg to new surface configuration\n"
                f"  set initial working directory of cfg to {applescript_str(cwd)}\n"
                f"  set initial input of cfg to {applescript_str(typed)} & linefeed\n"
                "  set w to new window with configuration cfg\n"
                "  activate\n"
                "  return id of w\n"
                "end tell"
            )
            return window_id, _read_tty(ttyfile)
        finally:
            if os.path.exists(ttyfile):
                os.unlink(ttyfile)


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


#: The apps the shift fully drives (open AND close), one per BUILTIN_TERMINALS name.
BUILTIN_SPAWNERS: dict[str, type[OsascriptTerminal]] = {
    cls.name: cls for cls in (AppleTerminal, ITerm2, Ghostty)
}


def make_spawner(terminal_app: str, custom: dict[str, str] | None = None) -> TerminalSpawner:
    if builtin := BUILTIN_SPAWNERS.get(terminal_app):
        return builtin()
    if custom and terminal_app in custom:
        return CommandTemplate(custom[terminal_app])
    return AppleTerminal()  # a setting that names nothing (removed app) falls back
