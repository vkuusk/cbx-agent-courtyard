"""`courtyard-invite`, the command-line register/install/remove (item 40): `--remove`
is the full undo the docs promise (files out, agent off the hub, like the WebUI's
remove), `--keep-registration` detaches the directory only."""

from __future__ import annotations

import httpx

from courtyard.adapters.claude_code import invite


def _run(capsys, *argv) -> str:
    invite.cli(list(argv))
    return capsys.readouterr().out


def test_remove_is_a_full_undo_and_keep_registration_is_not(live_hub, tmp_path, capsys):
    url = live_hub()
    workdir = tmp_path / "proj"
    workdir.mkdir()
    (workdir / ".git").mkdir()
    out = _run(
        capsys,
        "--hub",
        url,
        "--register",
        "--name",
        "cli-agent",
        "--type",
        "dummy",
        "--workdir",
        str(workdir),
    )
    assert "registered cli-agent" in out and (workdir / ".mcp.json").exists()
    assert (workdir / ".gitignore").exists() and ".gitignore updated" in out

    out = _run(capsys, "--hub", url, "--name", "cli-agent", "--remove", "--keep-registration")
    assert "stays registered" in out and not (workdir / ".mcp.json").exists()
    assert not (workdir / ".gitignore").exists()  # held only our lines
    assert httpx.get(f"{url}/api/agents/cli-agent").json()["removed_at"] is None

    # nothing left to take out of the directory: the registration still goes
    out = _run(capsys, "--hub", url, "--name", "cli-agent", "--remove")
    assert "nothing to take out" in out and "removed cli-agent from the hub" in out
    assert httpx.get(f"{url}/api/agents/cli-agent").json()["removed_at"] is not None

    # the full undo in one go
    _run(
        capsys,
        "--hub",
        url,
        "--register",
        "--name",
        "cli-agent",
        "--type",
        "dummy",
        "--workdir",
        str(workdir),
    )  # D36: the name is free again
    out = _run(capsys, "--hub", url, "--name", "cli-agent", "--remove")
    assert "removed the courtyard entry" in out and "removed cli-agent from the hub" in out
    assert not (workdir / ".mcp.json").exists()
