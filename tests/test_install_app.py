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


def test_install_says_which_database_it_found():
    assert (
        install.describe_database(0, 0, 0, "")
        == "fresh courtyard database (nothing registered yet)"
    )
    text = install.describe_database(3, 12, 4, "devops-team")
    assert text.startswith("EXISTING courtyard database found and used: 3 agent(s), 12 message(s)")
    assert "4 memory record(s), team devops-team" in text


def test_the_webui_opens_as_its_own_window(tmp_path):
    """Never a tab with the browser's decorations: the installed Dock app first, then
    Chrome in app mode (what make run-chrome does), then the default browser."""
    url = "http://127.0.0.1:2626"
    dock_app = tmp_path / "Agent Courtyard.app"
    chrome = tmp_path / "Google Chrome"
    assert install.webui_command(url, web_apps=(dock_app,), chrome=str(chrome)) == ["open", url]
    chrome.write_text("")
    assert install.webui_command(url, web_apps=(dock_app,), chrome=str(chrome)) == [
        str(chrome),
        f"--app={url}",
    ]
    dock_app.mkdir()
    assert install.webui_command(url, web_apps=(dock_app,), chrome=str(chrome)) == [
        "open",
        "-a",
        str(dock_app),
    ]


def test_the_summary_lists_every_step_and_repeats_warnings_in_full():
    steps = [
        ("the hub's environment (.venv)", "OK", []),
        ("local settings (.env)", "OK", [".env existed and was kept as is"]),
        (
            "postgres",
            "WARNING",
            ["EXISTING courtyard database found and used: 3 agent(s)", "shared"],
        ),
        ("the LaunchAgents", "OK", []),
    ]
    text = install.format_summary(steps)
    lines = text.splitlines()
    assert lines[0] == "*" * 60 and "Summary" in lines[1]
    assert "1. the hub's environment (.venv) - OK" in lines
    assert "2. local settings (.env) - OK:" in lines
    assert "3. postgres - WARNING:" in lines
    assert "  EXISTING courtyard database found and used: 3 agent(s)" in lines
    assert lines.count("--------") == 4  # one block around each step's details
    assert lines[-1] == "1 warning(s), see above"
    assert install.format_summary([("postgres", "OK", [])]).endswith("no warnings")


def test_install_records_the_existing_database_as_a_warning(monkeypatch):
    monkeypatch.setattr(install, "STEPS", [])
    monkeypatch.setattr(install, "sh", lambda *a, **k: None)
    monkeypatch.setattr(install, "read_env", dict)
    monkeypatch.setattr(install, "database_report", lambda: install.describe_database(3, 0, 0, "t"))
    install.prepare_postgres()
    monkeypatch.setattr(install, "database_report", lambda: install.describe_database(0, 0, 0, ""))
    install.prepare_postgres()
    (label, status, details), (_, fresh, _) = install.STEPS
    assert (label, status, fresh) == ("postgres", "WARNING", "OK")
    assert details[0].startswith("EXISTING courtyard database") and "make db-nuke" in "\n".join(
        details
    )


def test_install_warns_when_the_launchagent_ran_from_another_directory(tmp_path):
    """A second checkout's install takes the hub over from the first: said, not silent."""
    plist = tmp_path / "com.courtyard.hub.plist"
    assert install.previous_root(plist) is None  # nothing installed
    plist.write_text(install.render_plist(root=install.ROOT))
    assert install.previous_root(plist) is None  # same directory: a reinstall
    other = tmp_path / "elsewhere"
    plist.write_text(install.render_plist(root=other))
    assert install.previous_root(plist) == other
    warning = install.takeover_warning(other)
    assert str(other) in warning[0] and "no longer starts anything at login" in warning[2]
    plist.write_text("not a plist")
    assert install.previous_root(plist) is None


def test_install_opens_the_dock_app_when_it_is_already_installed(tmp_path):
    app = tmp_path / "Agent Courtyard.app"
    assert install.installed_dock_app(web_apps=(app,)) is None
    app.mkdir()
    assert install.installed_dock_app(web_apps=(app,)) == app
