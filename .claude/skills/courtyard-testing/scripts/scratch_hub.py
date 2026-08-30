#!/usr/bin/env python3
"""Start and stop a throwaway courtyard hub on a scratch database.

Use this instead of an ad-hoc hub launch whenever a check needs a hub of its
own: flipping courtyard-wide settings (discovery, defaults, team mode),
destructive data work, or anything else that must never touch the operator's
live hub. The operator's hub runs on port 2626; this script refuses that port
and stops only the exact pid it recorded. Never use pkill.

Usage (from the repo root):

    uv run python .claude/skills/courtyard-testing/scripts/scratch_hub.py start --name mycheck
    uv run python .claude/skills/courtyard-testing/scripts/scratch_hub.py stop --name mycheck
    uv run python .claude/skills/courtyard-testing/scripts/scratch_hub.py list

`start` brings the compose postgres up if needed, creates a scratch database
(courtyard_scratch_<name>), starts a hub on a free port, and prints the URL.
State (pid, log, port) lives in sandbox/scratch-<name>/. `stop` kills the
recorded pid and drops the scratch database.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
SANDBOX = REPO_ROOT / "sandbox"
OPERATOR_PORT = 2626


def die(msg: str) -> None:
    sys.exit(f"scratch_hub: {msg}")


def state_dir(name: str) -> Path:
    return SANDBOX / f"scratch-{name}"


def db_name(name: str) -> str:
    return "courtyard_scratch_" + name.replace("-", "_")


def psql(*statements: str) -> None:
    subprocess.run(
        ["docker", "exec", "courtyard-postgres", "psql", "-U", "courtyard", "-d", "postgres"]
        + [arg for s in statements for arg in ("-c", s)],
        check=True,
        capture_output=True,
    )


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return True


def healthy(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1):
            return True
    except Exception:
        return False


def start(name: str, port: int | None) -> None:
    d = state_dir(name)
    meta_file = d / "meta.json"
    if meta_file.exists():
        meta = json.loads(meta_file.read_text())
        if pid_alive(meta["pid"]):
            die(f"'{name}' is already running at http://127.0.0.1:{meta['port']}")
        shutil.rmtree(d)
    port = port or free_port()
    if port == OPERATOR_PORT:
        die(f"port {OPERATOR_PORT} belongs to the operator's live hub; pick another")

    subprocess.run(
        ["docker", "compose", "up", "-d", "--wait", "postgres"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )
    db = db_name(name)
    psql(f"DROP DATABASE IF EXISTS {db} WITH (FORCE)", f"CREATE DATABASE {db}")

    d.mkdir(parents=True)
    log = (d / "hub.log").open("w")
    env = {
        **os.environ,
        "DATABASE_URL": "postgresql://courtyard:courtyard@127.0.0.1:"
        + os.environ.get("COURTYARD_PG_PORT", "5432")
        + f"/{db}",
        "COURTYARD_PORT": str(port),
    }
    proc = subprocess.Popen(
        ["uv", "run", "courtyard-hub"], cwd=REPO_ROOT, env=env, stdout=log, stderr=log
    )
    meta_file.write_text(json.dumps({"pid": proc.pid, "port": port, "db": db}))

    for _ in range(75):
        if healthy(port):
            print(f"scratch hub '{name}' ready at http://127.0.0.1:{port}")
            print(f"  log : {d / 'hub.log'}")
            print(f"  stop: uv run python {Path(__file__).relative_to(REPO_ROOT)} stop --name {name}")
            return
        if proc.poll() is not None:
            break
        time.sleep(0.2)
    proc.terminate()
    tail = (d / "hub.log").read_text().splitlines()[-15:]
    die("hub did not become healthy; log tail:\n" + "\n".join(tail))


def stop(name: str) -> None:
    d = state_dir(name)
    meta_file = d / "meta.json"
    if not meta_file.exists():
        die(f"no scratch hub named '{name}' (see: list)")
    meta = json.loads(meta_file.read_text())
    if pid_alive(meta["pid"]):
        os.kill(meta["pid"], signal.SIGTERM)
        for _ in range(25):
            if not pid_alive(meta["pid"]):
                break
            time.sleep(0.2)
        else:
            os.kill(meta["pid"], signal.SIGKILL)
    psql(f"DROP DATABASE IF EXISTS {meta['db']} WITH (FORCE)")
    shutil.rmtree(d)
    print(f"scratch hub '{name}' stopped, database {meta['db']} dropped")


def list_hubs() -> None:
    rows = sorted(SANDBOX.glob("scratch-*/meta.json"))
    if not rows:
        print("no scratch hubs")
        return
    for meta_file in rows:
        meta = json.loads(meta_file.read_text())
        name = meta_file.parent.name.removeprefix("scratch-")
        status = "running" if pid_alive(meta["pid"]) else "dead (stop it to clean up)"
        print(f"{name:20} port {meta['port']:<6} pid {meta['pid']:<8} {status}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["start", "stop", "list"])
    parser.add_argument("--name", help="scratch hub name (lowercase letters, digits, hyphens)")
    parser.add_argument("--port", type=int, help="port for start (default: a free one)")
    args = parser.parse_args()
    if args.action == "list":
        list_hubs()
        return
    if not args.name or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", args.name):
        die("--name is required: lowercase letters, digits, hyphens")
    if args.action == "start":
        start(args.name, args.port)
    else:
        stop(args.name)


if __name__ == "__main__":
    main()