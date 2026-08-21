"""Writing an agent's `.mcp.json` into its workdir (design §8/D8, step 6d).

Pure filesystem tests against tmp dirs: the merge preserves other servers, the write is
0600 with a backup, and the reverse restores exactly what was there.
"""

from __future__ import annotations

import json
import stat

import pytest

from courtyard.hub.core import install
from courtyard.hub.core.errors import MalformedMcpJson, NothingToUninstall, WorkdirNotFound

CMD = "/abs/courtyard-claude-mcp"
HUB = "http://127.0.0.1:2626"


def read(path):
    return json.loads(path.read_text())


def mode(path):
    return stat.S_IMODE(path.stat().st_mode)


def test_server_block_matches_the_webui_config():
    block = install.server_block(CMD, HUB, "coding", "tok")
    assert block == {
        "command": CMD,
        "env": {
            "COURTYARD_HUB_URL": HUB,
            "COURTYARD_AGENT_NAME": "coding",
            "COURTYARD_TOKEN": "tok",
        },
    }


def test_install_into_empty_dir_creates_a_0600_file_no_backup(tmp_path):
    result = install.install(str(tmp_path), CMD, HUB, "coding", "tok")
    target = tmp_path / ".mcp.json"
    assert result.path == str(target)
    assert result.backed_up is None and result.replaced_server is False
    assert read(target)["mcpServers"]["courtyard"]["env"]["COURTYARD_TOKEN"] == "tok"
    assert mode(target) == 0o600
    assert not (tmp_path / ".mcp.json.courtyard-bak").exists()


def test_install_preserves_other_servers_and_keys_and_backs_up(tmp_path):
    target = tmp_path / ".mcp.json"
    target.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}, "misc": 1}))
    result = install.install(str(tmp_path), CMD, HUB, "coding", "tok")

    doc = read(target)
    assert set(doc["mcpServers"]) == {"other", "courtyard"}  # ours added, theirs kept
    assert doc["misc"] == 1  # unrelated top-level keys survive
    assert result.backed_up == str(tmp_path / ".mcp.json.courtyard-bak")
    assert read(tmp_path / ".mcp.json.courtyard-bak")["mcpServers"] == {"other": {"command": "x"}}
    assert result.replaced_server is False


def test_reinstall_replaces_our_entry_and_flags_it(tmp_path):
    install.install(str(tmp_path), CMD, HUB, "coding", "old")
    result = install.install(str(tmp_path), CMD, HUB, "coding", "new")
    assert result.replaced_server is True
    assert (
        read(tmp_path / ".mcp.json")["mcpServers"]["courtyard"]["env"]["COURTYARD_TOKEN"] == "new"
    )


def test_install_refuses_to_clobber_malformed_json(tmp_path):
    (tmp_path / ".mcp.json").write_text("{ not json")
    with pytest.raises(MalformedMcpJson):
        install.install(str(tmp_path), CMD, HUB, "coding", "tok")


def test_install_missing_workdir_raises(tmp_path):
    with pytest.raises(WorkdirNotFound):
        install.install(str(tmp_path / "nope"), CMD, HUB, "coding", "tok")


def test_uninstall_restores_the_backed_up_file(tmp_path):
    target = tmp_path / ".mcp.json"
    original = {"mcpServers": {"other": {"command": "x"}}}
    target.write_text(json.dumps(original))
    install.install(str(tmp_path), CMD, HUB, "coding", "tok")

    result = install.uninstall(str(tmp_path))
    assert result.restored_from_backup is True
    assert read(target) == original  # ours gone, theirs back exactly
    assert not (tmp_path / ".mcp.json.courtyard-bak").exists()  # backup consumed


def test_uninstall_without_backup_drops_only_our_key(tmp_path):
    # a file we merged into but whose backup was already cleaned up: hand-build that state
    target = tmp_path / ".mcp.json"
    target.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}, "courtyard": {}}}))
    result = install.uninstall(str(tmp_path))
    assert result.restored_from_backup is False and result.removed_server is True
    assert set(read(target)["mcpServers"]) == {"other"}


def test_uninstall_removes_the_file_when_it_held_only_us(tmp_path):
    install.install(str(tmp_path), CMD, HUB, "coding", "tok")  # fresh: no backup, only courtyard
    result = install.uninstall(str(tmp_path))
    assert result.removed_server is True
    assert not (tmp_path / ".mcp.json").exists()  # don't leave an empty {}


def test_uninstall_with_nothing_to_undo_raises(tmp_path):
    (tmp_path / ".mcp.json").write_text(json.dumps({"mcpServers": {"other": {}}}))
    with pytest.raises(NothingToUninstall):
        install.uninstall(str(tmp_path))
