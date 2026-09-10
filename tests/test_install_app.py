"""`make install`: the hub as a macOS LaunchAgent (scripts/install.py). The install itself
touches the operator's machine, so it stays a manual runbook check; what is tested here
is the rendered LaunchAgent and the wrapper's contract, which is where LaunchAgents break."""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import install


def test_plist_renders_absolute_paths_and_keepalive(tmp_path):
    text = install.render_plist(root=tmp_path, log=tmp_path / "sandbox" / "hub.log")
    plist = plistlib.loads(text.encode())
    assert plist["Label"] == "com.courtyard.hub"
    assert plist["ProgramArguments"] == ["/bin/sh", str(tmp_path / "scripts" / "hub-launch.sh")]
    assert plist["WorkingDirectory"] == str(tmp_path)
    assert plist["RunAtLoad"] is True and plist["KeepAlive"] is True
    assert plist["StandardOutPath"] == str(tmp_path / "sandbox" / "hub.log")
    # the hub learns it is supervised, which is what enables the Admin restart button
    assert plist["EnvironmentVariables"]["COURTYARD_SUPERVISED"] == "launchd"
    if shutil.which("plutil"):
        target = tmp_path / "com.courtyard.hub.plist"
        target.write_text(text)
        assert (
            subprocess.run(
                ["plutil", "-lint", str(target)], capture_output=True, check=False
            ).returncode
            == 0
        )


def test_launcher_sets_path_loads_env_waits_for_docker_and_execs_the_venv_hub():
    text = (ROOT / "scripts" / "hub-launch.sh").read_text()
    assert "/opt/homebrew/bin" in text and "/usr/local/bin" in text  # launchd's PATH is bare
    assert ". ./.env" in text
    assert "docker info" in text and "docker compose up -d --wait postgres" in text
    assert "exec .venv/bin/courtyard-hub" in text  # no uv needed at runtime
    if shutil.which("sh"):
        assert (
            subprocess.run(
                ["sh", "-n", str(ROOT / "scripts" / "hub-launch.sh")], check=False
            ).returncode
            == 0
        )


def test_install_script_is_standard_library_only():
    """It runs with the machine's python3 before the venv exists."""
    text = (ROOT / "scripts" / "install.py").read_text()
    for third_party in ("import httpx", "import psycopg", "import fastapi", "from courtyard"):
        assert third_party not in text


def test_env_file_parser_reads_the_port(tmp_path, monkeypatch):
    monkeypatch.setattr(install, "ROOT", tmp_path)
    assert install.hub_url() == "http://127.0.0.1:2626"
    (tmp_path / ".env").write_text(
        "# comment\nCOURTYARD_PORT=2727\nCOURTYARD_LOG_LEVEL='WARNING'\n"
    )
    assert install.read_env() == {"COURTYARD_PORT": "2727", "COURTYARD_LOG_LEVEL": "WARNING"}
    assert install.hub_url() == "http://127.0.0.1:2727"


@pytest.mark.skipif(sys.platform != "darwin", reason="launchctl is macOS")
def test_status_reports_without_an_install():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "install.py"), "status"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert (
        result.returncode == 0
        and "LaunchAgent :" in result.stdout
        and "hub         :" in result.stdout
    )


def test_tray_plist_runs_the_venv_app_with_the_root_in_its_environment(tmp_path):
    text = install.render_plist(
        root=tmp_path, log=tmp_path / "sandbox" / "tray.log", template=install.TRAY_TEMPLATE
    )
    plist = plistlib.loads(text.encode())
    assert plist["Label"] == "com.courtyard.tray"
    assert plist["ProgramArguments"] == [str(tmp_path / ".venv" / "bin" / "courtyard-tray")]
    assert plist["EnvironmentVariables"]["COURTYARD_ROOT"] == str(tmp_path)
    assert "/opt/homebrew/bin" in plist["EnvironmentVariables"]["PATH"]  # for `open`, docker
    assert plist["KeepAlive"] is True and plist["RunAtLoad"] is True


@pytest.mark.skipif(sys.platform != "darwin", reason="install.sh refuses anything but macOS")
def test_install_sh_unpacks_a_zip_package_into_an_empty_directory(tmp_path):
    """The one-command install, minus the download and the install itself: a zip from
    `make zip-package` lands flattened in the target directory, dotfiles included, the
    development-only paths left out by `.gitattributes`; a non-empty directory is refused."""
    zip_dir = tmp_path / "zip"
    zip_dir.mkdir()
    made = subprocess.run(
        [
            "git",
            "archive",
            "--worktree-attributes",  # the checkout's .gitattributes, committed or not
            "--format=zip",
            "--prefix=courtyard-test/",
            "-o",
            str(zip_dir / "c.zip"),
            "HEAD",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert made.returncode == 0, made.stderr
    target = tmp_path / "install-here"
    env = {
        **os.environ,
        "COURTYARD_ZIP": str(zip_dir / "c.zip"),
        "COURTYARD_DIR": str(target),
        "COURTYARD_UNPACK_ONLY": "1",
    }
    run = subprocess.run(
        ["sh", str(ROOT / "install.sh")], env=env, capture_output=True, text=True, check=False
    )
    if "docker is" in run.stderr or "python 3.14" in run.stderr:
        pytest.skip(f"prerequisite missing on this machine: {run.stderr.strip()}")
    assert run.returncode == 0, run.stderr
    assert f"unpacked into {target}" in run.stdout
    # files at HEAD (the archive is of the commit, so nothing uncommitted can be expected)
    for present in ("Makefile", ".env.default", ".python-version", "tests", "webui"):
        assert (target / present).exists(), present
    for absent in (".github", ".claude", "docs/planning", "docs/archived", ".gitattributes"):
        assert not (target / absent).exists(), absent
    assert not (target / "courtyard-test").exists()  # flattened

    again = subprocess.run(
        ["sh", str(ROOT / "install.sh")], env=env, capture_output=True, text=True, check=False
    )
    assert again.returncode != 0 and "is not empty" in again.stderr


def test_release_workflow_publishes_the_zip_package():
    text = (ROOT / ".github" / "workflows" / "release.yml").read_text()
    assert "make zip-package" in text and "courtyard.zip" in text and "gh release create" in text
    assert 'tags: ["v*"]' in text
