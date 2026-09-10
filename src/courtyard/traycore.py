"""The menu bar app's logic, without the menu bar (rumps stays in `tray.py`).

A small standalone process beside the hub: it runs the same commands `make hub-start`,
`hub-stop` and `hub-restart` run (scripts/install.py over launchd), asks the hub for its
health and the gate count, and starts or ends the shift over the API. Nothing here is
hub code, so the hub stays the same whether it runs on this machine or, later, remotely;
only this app is macOS-shaped.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path


def project_root() -> Path:
    """Where `scripts/install.py` and `.env` live: told by the LaunchAgent, else derived
    from this file (an editable install inside the checkout)."""
    told = os.environ.get("COURTYARD_ROOT")
    return Path(told) if told else Path(__file__).resolve().parents[2]


def read_env(root: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    env_file = root / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip("'\"")
    return values


@dataclass
class HubState:
    up: bool
    db: str | None = None
    pending: int = 0  # messages held at the gate
    shift: str | None = None  # off | starting | on (ShiftPhase)
    stale: bool = False  # D25: the shift reads on but nobody is home

    def line(self) -> str:
        if not self.up:
            return "hub: down"
        parts = [f"hub: up (db {self.db or '?'})"]
        if self.shift and self.shift != "off":
            parts.append(f"shift {self.shift}" + (" (nobody home)" if self.stale else ""))
        else:
            parts.append("no shift")
        parts.append(f"{self.pending} at the gate")
        return " · ".join(parts)

    def glyph(self) -> str:
        """What sits beside the icon in the menu bar: nothing when all is quiet, the gate
        count when something waits, a hollow dot when the hub is down."""
        if not self.up:
            return "○"
        return str(self.pending) if self.pending else ""


class HubControl:
    def __init__(self, root: Path | None = None):
        self.root = root or project_root()
        env = read_env(self.root)
        self.url = f"http://127.0.0.1:{env.get('COURTYARD_PORT', '2626')}"
        self.log = self.root / "sandbox" / "hub.log"
        self.installer = self.root / "scripts" / "install.py"

    # -- reads ---------------------------------------------------------------------------

    def _get(self, path: str, timeout: float = 2.0):
        with urllib.request.urlopen(self.url + path, timeout=timeout) as resp:
            return json.loads(resp.read())

    def _post(self, path: str, body: dict | None = None, timeout: float = 30.0):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            self.url + path,
            data=data,
            method="POST",
            headers={"Content-Type": "application/json"} if data else {},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else None

    def state(self) -> HubState:
        try:
            health = self._get("/api/health")
        except (urllib.error.URLError, OSError, ValueError):
            return HubState(up=False)
        state = HubState(up=True, db=health.get("db"))
        try:
            state.pending = len(self._get("/api/gate/pending"))
            shift = self._get("/api/shift")
            state.shift = shift.get("state")
            state.stale = bool(shift.get("stale"))
        except (urllib.error.URLError, OSError, ValueError, TypeError):
            pass
        return state

    # -- the make targets, as the tray runs them ------------------------------------------

    def command(self, action: str) -> list[str]:
        """`make hub-<action>` without make: the installer script it delegates to."""
        if action not in ("start", "stop", "restart", "status", "open"):
            raise ValueError(action)
        return [sys.executable, str(self.installer), action]

    def run(self, action: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            self.command(action), capture_output=True, text=True, cwd=self.root, check=False
        )

    # -- the shift -----------------------------------------------------------------------

    def start_shift(self) -> dict:
        return self._post("/api/shift/start")

    def end_shift(self, force: bool = False) -> dict | str:
        """The shift's end; without force the hub refuses while lines are mid-work
        (`shift_busy`), which the caller turns into a question."""
        try:
            return self._post("/api/shift/end", {"force": force})
        except urllib.error.HTTPError as exc:
            try:
                return json.loads(exc.read())["error"].get("code", "http_error")
            except (ValueError, KeyError, TypeError):
                return "http_error"

    def open_webui(self) -> None:
        """The board as its own window (the installed Dock app, else Chrome's app mode,
        else the default browser), decided by the install script so `make hub-open` and
        the menu agree."""
        subprocess.Popen(
            self.command("open"),
            cwd=self.root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def quit_command(self) -> list[str]:
        """Quit under launchd means unload: a plain exit would be restarted (KeepAlive)
        within seconds. The Courtyard Admin app in ~/Applications, `make hub-start` or the
        next login bring it back."""
        return ["launchctl", "bootout", f"gui/{os.getuid()}/com.courtyard.tray"]

    def quit_admin(self) -> bool:
        """True when launchd unloaded us (the process is ending); False when this is not
        the LaunchAgent (run by hand), so the caller just exits."""
        result = subprocess.run(self.quit_command(), capture_output=True, check=False)
        return result.returncode == 0

    def open_log(self) -> None:
        if self.log.exists():
            subprocess.Popen(["open", "-a", "Console", str(self.log)])
