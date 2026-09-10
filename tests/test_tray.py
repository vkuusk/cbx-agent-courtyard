"""The menu bar app's logic (`courtyard.traycore`): the buttons behind `make hub-*`, the
state line and glyph, the shift calls. The menu bar itself (rumps) is not driven here; the
runbook does that by hand."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from courtyard import traycore
from courtyard.traycore import HubControl, HubState


def test_state_line_and_glyph():
    assert HubState(up=False).line() == "hub: down"
    assert HubState(up=False).glyph() == "○"
    quiet = HubState(up=True, db="ok", pending=0, shift="off")
    assert quiet.line() == "hub: up (db ok) · no shift · 0 at the gate"
    assert quiet.glyph() == ""  # nothing beside the icon while all is quiet
    busy = HubState(up=True, db="ok", pending=3, shift="on")
    assert busy.line() == "hub: up (db ok) · shift on · 3 at the gate"
    assert busy.glyph() == "3"
    assert "(nobody home)" in HubState(up=True, shift="on", stale=True).line()


def test_the_buttons_run_the_installer_the_make_targets_run(tmp_path):
    control = HubControl(root=tmp_path)
    for action in ("start", "stop", "restart", "status", "open"):
        assert control.command(action) == [
            sys.executable,
            str(tmp_path / "scripts" / "install.py"),
            action,
        ]
    try:
        control.command("nuke")
    except ValueError:
        pass
    else:
        raise AssertionError("only the hub-* actions are buttons")


def test_root_and_port_come_from_the_launchagent_env_and_dotenv(tmp_path, monkeypatch):
    monkeypatch.setenv("COURTYARD_ROOT", str(tmp_path))
    assert traycore.project_root() == tmp_path
    (tmp_path / ".env").write_text("COURTYARD_PORT=2727\n")
    control = HubControl()
    assert control.root == tmp_path and control.url == "http://127.0.0.1:2727"
    monkeypatch.delenv("COURTYARD_ROOT")
    assert traycore.project_root() == Path(traycore.__file__).resolve().parents[2]


def test_state_against_a_live_hub(live_hub, tmp_path):
    url = live_hub()
    (tmp_path / ".env").write_text(f"COURTYARD_PORT={url.rsplit(':', 1)[-1]}\n")
    control = HubControl(root=tmp_path)
    state = control.state()
    assert state.up is True and state.db == "ok"
    assert state.shift == "off" and state.pending == 0
    # the shift, through the same buttons the tray offers
    assert control.start_shift()["state"] in ("starting", "on")
    assert control.state().shift in ("starting", "on")
    assert control.end_shift(force=True)["state"] == "off"
    down = HubControl(root=tmp_path)
    down.url = "http://127.0.0.1:9"
    assert down.state().up is False


def test_the_tray_is_a_menu_bar_app_with_the_courtyard_icon(tmp_path):
    """No Dock tile or task-switcher entry (accessory policy); the app icon, shown by its
    alerts, is the courtyard's when the file is there, and nothing is set when it is not."""
    tray = pytest.importorskip("courtyard.tray")

    class FakeApp:
        policy = None
        icon = None

        def setActivationPolicy_(self, policy):
            self.policy = policy

        def setApplicationIconImage_(self, image):
            self.icon = image

    loaded = []
    load = lambda path: loaded.append(path) or f"image:{path}"
    app = FakeApp()
    tray.keep_out_of_the_dock(app, tmp_path / "missing.png", load)
    assert app.policy == tray.ACCESSORY and app.icon is None and loaded == []
    icon = tmp_path / "icon-512.png"
    icon.write_bytes(b"png")
    tray.keep_out_of_the_dock(FakeApp(), None, load)
    app = FakeApp()
    tray.keep_out_of_the_dock(app, icon, load)
    assert app.icon == f"image:{icon}" and loaded == [str(icon)]


def test_quit_unloads_the_tray_launchagent_instead_of_exiting(tmp_path):
    """A plain exit under launchd is a restart (KeepAlive); Quit must bootout."""
    import os

    control = HubControl(root=tmp_path)
    assert control.quit_command() == [
        "launchctl",
        "bootout",
        f"gui/{os.getuid()}/com.courtyard.tray",
    ]
