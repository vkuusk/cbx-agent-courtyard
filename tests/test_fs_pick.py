"""The native directory picker: unit tests with a stubbed osascript (a real dialog
cannot run in CI), plus the API contract the WebUI's fallback relies on."""

from __future__ import annotations

import subprocess
import sys
from types import SimpleNamespace

import pytest

from courtyard.hub.core import fs_pick
from courtyard.hub.core.fs_pick import NativePickerUnavailable, pick_directory

darwin_only = pytest.mark.skipif(sys.platform != "darwin", reason="native picker is macOS-only")


@darwin_only
def test_picked_path_comes_back(monkeypatch):
    def fake_run(cmd, **kwargs):
        assert cmd[0] == "osascript" and cmd[-1] == "pick one"  # prompt rides argv, unescaped
        return SimpleNamespace(returncode=0, stdout="/Users/x/teams/\n", stderr="")

    monkeypatch.setattr(fs_pick.subprocess, "run", fake_run)
    assert pick_directory("pick one") == "/Users/x/teams/"


@darwin_only
def test_cancel_is_none_not_an_error(monkeypatch):
    monkeypatch.setattr(
        fs_pick.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(
            returncode=1, stdout="", stderr="execution error: User canceled. (-128)"
        ),
    )
    assert pick_directory("x") is None


@darwin_only
def test_other_osascript_failures_mean_unavailable(monkeypatch):
    monkeypatch.setattr(
        fs_pick.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="no GUI session"),
    )
    with pytest.raises(NativePickerUnavailable):
        pick_directory("x")
    monkeypatch.setattr(
        fs_pick.subprocess,
        "run",
        lambda *a, **k: (_ for _ in ()).throw(subprocess.TimeoutExpired("osascript", 1)),
    )
    with pytest.raises(NativePickerUnavailable):
        pick_directory("x")


def test_env_switch_disables_the_native_picker(monkeypatch):
    monkeypatch.setenv("COURTYARD_NATIVE_PICKER", "0")
    with pytest.raises(NativePickerUnavailable):
        pick_directory("x")


def test_api_answers_the_fallback_code(client, monkeypatch):
    """The WebUI opens its own browse dialog exactly on this code."""
    monkeypatch.setenv("COURTYARD_NATIVE_PICKER", "0")
    resp = client.post("/api/fs/pick-dir", json={"prompt": "anything"})
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "native_picker_unavailable"


@darwin_only
def test_api_returns_the_path_and_null_on_cancel(client, monkeypatch):
    monkeypatch.setattr(
        fs_pick.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="/tmp/somewhere\n", stderr=""),
    )
    assert client.post("/api/fs/pick-dir", json={}).json() == {"path": "/tmp/somewhere"}
    monkeypatch.setattr(
        fs_pick.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="(-128)"),
    )
    assert client.post("/api/fs/pick-dir", json={}).json() == {"path": None}
