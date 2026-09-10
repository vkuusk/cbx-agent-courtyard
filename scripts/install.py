#!/usr/bin/env python3
"""Install the courtyard hub as a macOS LaunchAgent, and take it out again.

Standard library only, so it runs with whatever `python3` the machine has before the
project's own environment exists. Everything it changes outside this directory is one
file: `~/Library/LaunchAgents/com.courtyard.hub.plist`. Inside it: `.venv`, `.env` (copied
from `.env.default` if missing) and `sandbox/hub.log`. Docker gets the postgres image and
a volume named `courtyard_courtyard-pgdata` (the compose project is named `courtyard`).

    make install                # venv, .env, postgres image, LaunchAgent; the hub is up
    make hub-start | hub-stop | hub-restart | hub-status | hub-open
    make uninstall              # LaunchAgent gone, containers down, .venv gone; data kept
    make uninstall PURGE=1      # ... and the postgres volume and image removed too

Under launchd the hub starts at login and comes back if it dies (KeepAlive). Stop means
unload: the hub stays down until `make hub-start` or the next `make install`.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LABEL = "com.courtyard.hub"
PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
TEMPLATE = ROOT / "scripts" / "launchd" / f"{LABEL}.plist.template"
LAUNCHER = ROOT / "scripts" / "hub-launch.sh"
LOG = ROOT / "sandbox" / "hub.log"
# the menu bar app (courtyard-tray): its own LaunchAgent, so it is there when the hub is not
TRAY_LABEL = "com.courtyard.tray"
TRAY_PLIST = PLIST.parent / f"{TRAY_LABEL}.plist"
TRAY_TEMPLATE = TEMPLATE.parent / f"{TRAY_LABEL}.plist.template"
TRAY_LOG = ROOT / "sandbox" / "tray.log"
REQUIRED_PYTHON = (3, 14)


def say(text: str) -> None:
    print(text, flush=True)


def sh(
    cmd: list[str], check: bool = True, quiet: bool = False, **kw
) -> subprocess.CompletedProcess:
    if not quiet:
        say("  $ " + " ".join(cmd))
    return subprocess.run(cmd, check=check, text=True, **kw)


def domain() -> str:
    return f"gui/{os.getuid()}"


def read_env() -> dict[str, str]:
    """The few `.env` values this script needs; a missing file means the defaults."""
    values: dict[str, str] = {}
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip("'\"")
    return values


def hub_url() -> str:
    return f"http://127.0.0.1:{read_env().get('COURTYARD_PORT', '2626')}"


def health(url: str, timeout: float = 2.0) -> dict | None:
    try:
        with urllib.request.urlopen(url + "/api/health", timeout=timeout) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, OSError, ValueError):
        return None


def render_plist(root: Path = ROOT, log: Path = LOG, template: Path = TEMPLATE) -> str:
    """A LaunchAgent: launchd runs the program in this directory, at login and whenever it
    exits; launchd's environment is nearly empty, so PATH is set explicitly."""
    return (
        template.read_text()
        .replace("{{ROOT}}", str(root))
        .replace("{{LAUNCHER}}", str(root / "scripts" / "hub-launch.sh"))
        .replace("{{LOG}}", str(log))
    )


def loaded(label: str = LABEL) -> bool:
    return (
        subprocess.run(
            ["launchctl", "print", f"{domain()}/{label}"],
            capture_output=True,
            text=True,
            check=False,
        ).returncode
        == 0
    )


# -- steps -------------------------------------------------------------------------------


def check_prerequisites() -> None:
    if sys.platform != "darwin":
        sys.exit("the LaunchAgent install is macOS only (the hub itself runs anywhere with Docker)")
    if shutil.which("docker") is None:
        sys.exit(
            "docker is not on PATH: install Docker Desktop or Colima, set it to start at login"
        )
    if subprocess.run(["docker", "info"], capture_output=True, check=False).returncode != 0:
        sys.exit("docker is installed but not running: start it (and set it to start at login)")


def python_for_venv() -> str:
    """The interpreter the venv is built from: the pinned major.minor, wherever it is."""
    want = f"python{REQUIRED_PYTHON[0]}.{REQUIRED_PYTHON[1]}"
    for candidate in (want, "python3"):
        path = shutil.which(candidate)
        if path is None:
            continue
        version = subprocess.run(
            [path, "-c", "import sys; print(sys.version_info[0], sys.version_info[1])"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.split()
        if tuple(int(v) for v in version) >= REQUIRED_PYTHON:
            return path
    sys.exit(
        f"python {REQUIRED_PYTHON[0]}.{REQUIRED_PYTHON[1]} is required (brew install python@3.14)"
    )


def make_venv() -> None:
    say("1. the hub's environment (.venv)")
    if shutil.which("uv"):
        # dev tools included so a clone stays a working checkout; `tray` = the menu bar app
        sh(["uv", "sync", "--extra", "tray"], cwd=ROOT)
        return
    python = python_for_venv()
    if not (ROOT / ".venv").exists():
        sh([python, "-m", "venv", ".venv"], cwd=ROOT)
    sh([str(ROOT / ".venv" / "bin" / "pip"), "install", "-q", "-e", ".[tray]"], cwd=ROOT)


def make_env_file() -> None:
    say("2. local settings (.env)")
    target = ROOT / ".env"
    if target.exists():
        say("  .env exists, kept as is")
    else:
        shutil.copy(ROOT / ".env.default", target)
        say("  .env created from .env.default (edit it for ports, log level, embeddings)")


def prepare_postgres() -> None:
    say("3. postgres (docker compose)")
    sh(["docker", "compose", "up", "-d", "--wait", "postgres"], cwd=ROOT)


def write_agent() -> None:
    say("4. the LaunchAgents (the hub, and the menu bar app)")
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    PLIST.write_text(render_plist())
    TRAY_PLIST.write_text(render_plist(log=TRAY_LOG, template=TRAY_TEMPLATE))
    LAUNCHER.chmod(0o755)
    for plist in (PLIST, TRAY_PLIST):
        sh(["plutil", "-lint", str(plist)], quiet=True, capture_output=True)
        say(f"  wrote {plist}")


def load_agent(label: str = LABEL, plist: Path = PLIST) -> None:
    if loaded(label):
        sh(["launchctl", "bootout", f"{domain()}/{label}"], check=False, capture_output=True)
        time.sleep(1)
    sh(["launchctl", "bootstrap", domain(), str(plist)])
    sh(["launchctl", "kickstart", "-k", f"{domain()}/{label}"], check=False, capture_output=True)


def wait_for_hub(seconds: float = 60.0) -> dict | None:
    url = hub_url()
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        report = health(url)
        if report:
            return report
        time.sleep(1.0)
    return None


def install() -> None:
    check_prerequisites()
    make_venv()
    make_env_file()
    prepare_postgres()
    write_agent()
    say("5. starting the hub and the menu bar app under launchd")
    load_agent()
    load_agent(TRAY_LABEL, TRAY_PLIST)
    report = wait_for_hub()
    url = hub_url()
    if not report:
        sys.exit(f"the hub did not answer at {url} within a minute; see {LOG}")
    say(f"  hub up at {url} (status {report.get('status')}, db {report.get('db')})")
    say("")
    say("Done. The hub now starts at login and restarts if it dies.")
    say("The Courtyard icon in the menu bar has the buttons: Open WebUI, Start / Stop /")
    say("Restart hub, Start / End shift; beside it, the number of messages waiting at the gate.")
    say(f"Logs: {LOG}, {TRAY_LOG}")
    say("")
    say("6. opening the WebUI in your browser")
    say("  It asks whether to keep the courtyard in your Dock: Chrome installs it from the")
    say("  button, Safari from File > Add to Dock. The Dock icon counts what waits for you.")
    subprocess.run(["open", url], check=False)
    say("")
    say("make hub-status | hub-stop | hub-start | hub-restart | hub-open ; make uninstall")


def registered_workdirs() -> list[str]:
    try:
        with urllib.request.urlopen(hub_url() + "/api/agents", timeout=3) as resp:
            agents = json.loads(resp.read())
    except (urllib.error.URLError, OSError, ValueError):
        return []
    return sorted(
        f"{a['name']}: {a['workdir']}"
        for a in agents
        if a.get("workdir") and not a.get("removed_at") and a.get("type") != "human"
    )


def uninstall(purge: bool) -> None:
    say("1. the agents' project directories (not touched; listed so you can clean them)")
    workdirs = registered_workdirs()
    for line in workdirs or ["  (hub not running or no agents registered)"]:
        say("  " + line if not line.startswith("  ") else line)
    if workdirs:
        say("  each holds .mcp.json, .claude/settings.local.json and start-with-courtyard.sh;")
        say(
            "  remove them with: .venv/bin/courtyard-invite --name <agent> --remove  (before step 3)"
        )
    say("2. the LaunchAgents")
    for label, plist in ((TRAY_LABEL, TRAY_PLIST), (LABEL, PLIST)):
        if loaded(label):
            sh(["launchctl", "bootout", f"{domain()}/{label}"], check=False)
        if plist.exists():
            plist.unlink()
            say(f"  removed {plist}")
    say("3. containers" + (" and the data volume" if purge else " (data volume kept)"))
    cmd = ["docker", "compose", "--profile", "tools", "down"]
    if purge:
        cmd.append("-v")
    sh(cmd, cwd=ROOT, check=False)
    if purge:
        sh(
            ["docker", "image", "rm", "pgvector/pgvector:pg18", "adminer:latest"],
            check=False,
            capture_output=True,
        )
    say("4. the environment (.venv)")
    shutil.rmtree(ROOT / ".venv", ignore_errors=True)
    say("")
    say(
        "Uninstalled. Kept: this directory, .env, sandbox/ logs"
        + ("" if purge else ", the postgres data volume")
    )
    say("Remove the Dock app by dragging it out of the Dock (Safari) or from chrome://apps.")
    say("The menu bar icon is gone with its LaunchAgent.")


def status() -> None:
    url = hub_url()
    say(f"LaunchAgent : {'loaded' if loaded() else 'not loaded'} ({PLIST})")
    say(f"menu bar    : {'loaded' if loaded(TRAY_LABEL) else 'not loaded'} ({TRAY_PLIST})")
    report = health(url)
    say(f"hub         : {url} " + (f"up (db {report.get('db')})" if report else "down"))
    if LOG.exists():
        say(f"log         : {LOG}")


def start() -> None:
    if not PLIST.exists():
        sys.exit("not installed: run `make install` first")
    if loaded():
        say("already loaded; use `make hub-restart` to restart it")
        return
    sh(["launchctl", "bootstrap", domain(), str(PLIST)])
    report = wait_for_hub()
    say(f"hub {'up' if report else 'did not answer in time, see ' + str(LOG)} at {hub_url()}")


def stop() -> None:
    if not loaded():
        say("not loaded (already stopped)")
        return
    sh(["launchctl", "bootout", f"{domain()}/{LABEL}"])
    say(
        "hub stopped; `make hub-start` brings it back (and so does the next login after `make install`)"
    )


def restart() -> None:
    if not loaded():
        start()
        return
    sh(["launchctl", "kickstart", "-k", f"{domain()}/{LABEL}"])
    report = wait_for_hub()
    say(f"hub {'up' if report else 'did not answer in time, see ' + str(LOG)} at {hub_url()}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("install")
    un = sub.add_parser("uninstall")
    un.add_argument(
        "--purge", action="store_true", help="also remove the postgres volume and images"
    )
    sub.add_parser("status")
    sub.add_parser("start")
    sub.add_parser("stop")
    sub.add_parser("restart")
    sub.add_parser("open")
    sub.add_parser("render-plist")
    args = parser.parse_args()
    if args.command == "install":
        install()
    elif args.command == "uninstall":
        uninstall(args.purge)
    elif args.command == "status":
        status()
    elif args.command == "start":
        start()
    elif args.command == "stop":
        stop()
    elif args.command == "restart":
        restart()
    elif args.command == "open":
        subprocess.run(["open", hub_url()], check=False)
    elif args.command == "render-plist":
        print(render_plist(), end="")


if __name__ == "__main__":
    main()
