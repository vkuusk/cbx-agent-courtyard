"""Runbook check: COURTYARD_LOG_LEVEL and access-log severity.

The hub's stdout verbosity is one knob, COURTYARD_LOG_LEVEL (INFO default, WARNING,
ERROR; DEBUG works too). Request lines log at their real severity — below 400 INFO,
4xx WARNING, 5xx ERROR — where uvicorn's own access log printed everything, a 422
included, at INFO.

Runs against its OWN throwaway hub on a scratch database, twice:

  1. LOG_LEVEL unset (INFO): a 200 request line prints at INFO, a deliberate 422
     (a team add without a name) prints at WARNING
  2. LOG_LEVEL=WARNING: the 200 line does not print at all, the 422 still does

Needs the compose postgres up (`make db-up`). Run:
    uv run python scripts/runbook/log_level.py
"""

import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

PORT = 3636
HUB = f"http://127.0.0.1:{PORT}"
DB_NAME = "courtyard_loglevel_rb"
PG_PORT = os.environ.get("COURTYARD_PG_PORT", "5432")
DB = f"postgresql://courtyard:courtyard@127.0.0.1:{PG_PORT}/{DB_NAME}"


def hr(title):
    print("\n" + "=" * 78 + f"\n{title}\n" + "=" * 78)


def psql(*statements):
    subprocess.run(
        ["docker", "exec", "courtyard-postgres", "psql", "-U", "courtyard", "-d", "postgres"]
        + [arg for s in statements for arg in ("-c", s)],
        check=True,
        capture_output=True,
    )


def request(path, method="GET", data=None):
    req = urllib.request.Request(HUB + path, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code


def run_hub(log_level, label):
    env = {**os.environ, "DATABASE_URL": DB, "COURTYARD_PORT": str(PORT)}
    env.pop("COURTYARD_LOG_LEVEL", None)
    if log_level:
        env["COURTYARD_LOG_LEVEL"] = log_level
    fd, out_path = tempfile.mkstemp(suffix=".log")
    with os.fdopen(fd, "w") as out:
        proc = subprocess.Popen(
            ["uv", "run", "courtyard-hub"], env=env, stdout=out, stderr=subprocess.STDOUT
        )
        try:
            for _ in range(60):
                try:
                    request("/api/health")
                    break
                except OSError:
                    time.sleep(0.2)
            else:
                sys.exit("throwaway hub did not start")
            ok = request("/api/health")
            refused = request("/api/teams", "POST", b'{"charter_dir": "/tmp"}')
            time.sleep(0.5)  # let the lines land in the file
        finally:
            proc.terminate()
            proc.wait()
    lines = Path(out_path).read_text().splitlines()
    os.unlink(out_path)
    access = [ln for ln in lines if "courtyard.access" in ln]
    hr(label)
    print(f"requests made     : GET /api/health -> {ok}, POST /api/teams (no name) -> {refused}")
    print("access lines seen :")
    for ln in access or ["  (none)"]:
        print(f"  {ln}")
    return access


psql(f"DROP DATABASE IF EXISTS {DB_NAME} WITH (FORCE)", f"CREATE DATABASE {DB_NAME}")
try:
    info_lines = run_hub(None, "1. DEFAULT (INFO): EVERY LINE PRINTS, THE 422 AT WARNING")
    ok = any("INFO" in ln and "/api/health" in ln for ln in info_lines) and any(
        "WARNING" in ln and "422" in ln for ln in info_lines
    )
    print(f"checkpoint        : {'OK' if ok else 'MISMATCH'} — 200 at INFO, 422 at WARNING")

    warn_lines = run_hub("WARNING", "2. LOG_LEVEL=WARNING: THE 200 LINE IS GONE, THE 422 STAYS")
    ok = not any("/api/health" in ln for ln in warn_lines) and any(
        "WARNING" in ln and "422" in ln for ln in warn_lines
    )
    print(f"checkpoint        : {'OK' if ok else 'MISMATCH'} — failures visible, noise quiet")
finally:
    psql(f"DROP DATABASE IF EXISTS {DB_NAME} WITH (FORCE)")
    print("\n(throwaway hub stopped, scratch database dropped.)")
