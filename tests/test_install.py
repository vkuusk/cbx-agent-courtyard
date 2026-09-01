"""Writing an agent's `.mcp.json` and `.claude/settings.local.json` (steps 6d + WP-A/D21).

Pure filesystem tests against tmp dirs: the merges preserve what was there, the token
file is 0600 with a backup, and the reverse restores exactly what was there — for the
settings, removing only what install adds.
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


# -- the agent-side profile: .claude/settings.local.json (WP-A, D21) -------------------


def settings_path(tmp_path):
    return tmp_path / ".claude" / "settings.local.json"


def test_install_writes_the_settings_profile(tmp_path):
    result = install.install(str(tmp_path), CMD, HUB, "coding", "tok", model="sonnet")
    target = settings_path(tmp_path)
    assert result.settings_path == str(target)
    assert result.settings_backed_up is None
    doc = read(target)
    assert doc["permissions"]["allow"] == ["mcp__courtyard"]  # no per-send prompt (7.2)
    assert doc["model"] == "sonnet"  # item 1
    assert doc["statusLine"]["command"] == "echo '⏺ coding · courtyard'"  # item 2


def test_install_without_model_leaves_model_unset(tmp_path):
    install.install(str(tmp_path), CMD, HUB, "coding", "tok")
    assert "model" not in read(settings_path(tmp_path))


def test_install_merges_settings_and_never_clobbers_a_status_line(tmp_path):
    sdir = tmp_path / ".claude"
    sdir.mkdir()
    original = {
        "permissions": {"allow": ["Bash(ls:*)"], "deny": ["WebFetch"]},
        "statusLine": {"type": "command", "command": "my-own-line"},
        "model": "opus",
    }
    settings_path(tmp_path).write_text(json.dumps(original))
    result = install.install(str(tmp_path), CMD, HUB, "coding", "tok", model="sonnet")
    doc = read(settings_path(tmp_path))
    assert doc["permissions"]["allow"] == ["Bash(ls:*)", "mcp__courtyard"]  # appended
    assert doc["permissions"]["deny"] == ["WebFetch"]  # untouched
    assert doc["statusLine"] == original["statusLine"]  # theirs, kept
    assert doc["model"] == "sonnet"  # the operator's declared intent wins
    assert result.settings_backed_up == str(sdir / "settings.local.json.courtyard-bak")
    assert read(sdir / "settings.local.json.courtyard-bak") == original


def test_reinstall_does_not_duplicate_the_allow_rule(tmp_path):
    install.install(str(tmp_path), CMD, HUB, "coding", "tok")
    install.install(str(tmp_path), CMD, HUB, "coding", "tok")
    assert read(settings_path(tmp_path))["permissions"]["allow"].count("mcp__courtyard") == 1


def test_uninstall_restores_the_settings_backup(tmp_path):
    sdir = tmp_path / ".claude"
    sdir.mkdir()
    original = {"model": "opus"}
    settings_path(tmp_path).write_text(json.dumps(original))
    install.install(str(tmp_path), CMD, HUB, "coding", "tok")

    result = install.uninstall(str(tmp_path))
    assert result.settings_restored is True
    assert read(settings_path(tmp_path)) == original
    assert not (sdir / "settings.local.json.courtyard-bak").exists()  # backup consumed


def test_uninstall_without_settings_backup_removes_only_ours(tmp_path):
    # the merged state whose backup was already cleaned up: hand-build it
    (tmp_path / ".claude").mkdir()
    settings_path(tmp_path).write_text(
        json.dumps(
            {
                "permissions": {"allow": ["mcp__courtyard", "Bash(ls:*)"]},
                "statusLine": install.status_line("coding"),
                "model": "sonnet",
            }
        )
    )
    (tmp_path / ".mcp.json").write_text(json.dumps({"mcpServers": {"courtyard": {}}}))
    result = install.uninstall(str(tmp_path))
    assert result.settings_cleaned is True
    doc = read(settings_path(tmp_path))
    assert doc["permissions"]["allow"] == ["Bash(ls:*)"]  # ours gone, theirs kept
    assert "statusLine" not in doc  # ours (STATUS_MARK), removed
    assert doc["model"] == "sonnet"  # left as-is: may be hand-tuned, and it is harmless


def test_uninstall_keeps_a_foreign_status_line(tmp_path):
    (tmp_path / ".claude").mkdir()
    theirs = {"type": "command", "command": "my-own-line"}
    settings_path(tmp_path).write_text(
        json.dumps({"permissions": {"allow": ["mcp__courtyard"]}, "statusLine": theirs})
    )
    (tmp_path / ".mcp.json").write_text(json.dumps({"mcpServers": {"courtyard": {}}}))
    install.uninstall(str(tmp_path))
    assert read(settings_path(tmp_path))["statusLine"] == theirs


def test_uninstall_removes_a_settings_file_that_held_only_ours(tmp_path):
    install.install(str(tmp_path), CMD, HUB, "coding", "tok")  # fresh: profile only
    install.uninstall(str(tmp_path))
    assert not settings_path(tmp_path).exists()  # don't leave an empty {}


def test_reinstall_under_a_new_name_updates_our_status_line(tmp_path):
    """Item 19 (bug, 2026-08-26): a workdir re-registered under a new name kept
    announcing the old one — the non-clobber rule protected OUR stale line. A line
    matching STATUS_MARK is ours and follows the current name; a hand-written one is
    still never touched (covered by the test above)."""
    install.install(str(tmp_path), "cmd", "http://127.0.0.1:2626", "old-name", "tok-1")
    install.install(str(tmp_path), "cmd", "http://127.0.0.1:2626", "new-name", "tok-2")
    doc = json.loads((tmp_path / ".claude" / "settings.local.json").read_text())
    assert doc["statusLine"]["command"] == "echo '⏺ new-name · courtyard'"


class TestStartScript:
    """Item 35: `start-with-courtyard.sh` — the human launch wrapper."""

    def test_install_writes_an_executable_wrapper_with_flag_and_model(self, tmp_path):
        result = install.install(str(tmp_path), CMD, HUB, "coding", "tok", model="haiku")
        script = tmp_path / "start-with-courtyard.sh"
        assert result.script_path == str(script)
        assert result.script_backed_up is None
        text = script.read_text()
        assert text.startswith("#!/bin/sh\n")
        assert "--dangerously-load-development-channels server:courtyard" in text
        assert "--model haiku" in text
        assert '"$@"' in text  # extra flags pass through
        assert mode(script) & 0o111  # executable

    def test_reinstall_regenerates_our_script_without_backing_it_up(self, tmp_path):
        install.install(str(tmp_path), CMD, HUB, "coding", "tok", model="haiku")
        install.install(str(tmp_path), CMD, HUB, "coding", "tok", model="opus")
        script = tmp_path / "start-with-courtyard.sh"
        assert "--model opus" in script.read_text()  # follows the model change
        assert not (tmp_path / "start-with-courtyard.sh.courtyard-bak").exists()

    def test_a_foreign_script_of_that_name_is_backed_up_and_survives_reinstalls(self, tmp_path):
        theirs = tmp_path / "start-with-courtyard.sh"
        theirs.write_text("#!/bin/sh\necho my own thing\n")
        install.install(str(tmp_path), CMD, HUB, "coding", "tok")
        backup = tmp_path / "start-with-courtyard.sh.courtyard-bak"
        assert backup.read_text() == "#!/bin/sh\necho my own thing\n"
        install.install(str(tmp_path), CMD, HUB, "coding", "tok")  # again: backup untouched
        assert backup.read_text() == "#!/bin/sh\necho my own thing\n"

    def test_uninstall_removes_our_script(self, tmp_path):
        install.install(str(tmp_path), CMD, HUB, "coding", "tok")
        result = install.uninstall(str(tmp_path))
        assert result.script_removed is True and result.script_restored is False
        assert not (tmp_path / "start-with-courtyard.sh").exists()

    def test_uninstall_restores_a_backed_up_foreign_script(self, tmp_path):
        theirs = tmp_path / "start-with-courtyard.sh"
        theirs.write_text("#!/bin/sh\necho my own thing\n")
        install.install(str(tmp_path), CMD, HUB, "coding", "tok")
        result = install.uninstall(str(tmp_path))
        assert result.script_restored is True and result.script_removed is False
        assert theirs.read_text() == "#!/bin/sh\necho my own thing\n"
        assert not (tmp_path / "start-with-courtyard.sh.courtyard-bak").exists()

    def test_uninstall_never_touches_a_foreign_script_without_backup(self, tmp_path):
        install.install(str(tmp_path), CMD, HUB, "coding", "tok")
        script = tmp_path / "start-with-courtyard.sh"
        script.write_text("#!/bin/sh\nrewritten by hand, no courtyard marker\n")
        result = install.uninstall(str(tmp_path))
        assert result.script_removed is False
        assert "rewritten by hand" in script.read_text()
