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


class TestSessionStartHook:
    """D40: the one hook. Written into the profile, ours by its command's name, kept
    beside foreign hooks, replaced in place, removed on uninstall."""

    def hooks(self, tmp_path):
        return read(settings_path(tmp_path)).get("hooks", {})

    def test_install_writes_the_hook_with_hub_and_name(self, tmp_path):
        install.install(str(tmp_path), CMD, HUB, "coding", "tok")
        (entry,) = self.hooks(tmp_path)["SessionStart"]
        assert entry["matcher"] == "startup|resume|clear|compact|fork"
        (hook,) = entry["hooks"]
        assert hook["type"] == "command" and hook["timeout"] == 5
        assert hook["command"].endswith(f"courtyard-claude-context --hub {HUB} --name coding")
        assert hook["command"].startswith("/")  # absolute: Claude Code's cwd is the project

    def test_foreign_hooks_are_kept_and_ours_is_replaced_in_place(self, tmp_path):
        (tmp_path / ".claude").mkdir()
        theirs = {"matcher": "startup", "hooks": [{"type": "command", "command": "my-hook.sh"}]}
        stop = {"hooks": [{"type": "command", "command": "notify.sh"}]}
        settings_path(tmp_path).write_text(
            json.dumps({"hooks": {"SessionStart": [theirs], "Stop": [stop]}})
        )
        install.install(str(tmp_path), CMD, HUB, "old-name", "tok-1")
        install.install(str(tmp_path), CMD, HUB, "new-name", "tok-2")
        hooks = self.hooks(tmp_path)
        assert hooks["Stop"] == [stop]
        assert hooks["SessionStart"][0] == theirs
        assert len(hooks["SessionStart"]) == 2  # ours once, not once per install
        assert hooks["SessionStart"][1]["hooks"][0]["command"].endswith("--name new-name")

    def test_uninstall_removes_only_our_hook(self, tmp_path):
        (tmp_path / ".claude").mkdir()
        theirs = {"matcher": "startup", "hooks": [{"type": "command", "command": "my-hook.sh"}]}
        settings_path(tmp_path).write_text(json.dumps({"hooks": {"SessionStart": [theirs]}}))
        install.install(str(tmp_path), CMD, HUB, "coding", "tok")
        (settings_path(tmp_path).parent / "settings.local.json.courtyard-bak").unlink()
        (tmp_path / ".mcp.json").write_text(json.dumps({"mcpServers": {"courtyard": {}}}))
        result = install.uninstall(str(tmp_path))
        assert result.settings_cleaned is True
        doc = read(settings_path(tmp_path))
        assert doc["hooks"] == {"SessionStart": [theirs]}
        assert "statusLine" not in doc and "permissions" not in doc

    def test_uninstall_drops_the_hooks_key_when_only_ours_was_there(self, tmp_path):
        (tmp_path / ".claude").mkdir()
        settings_path(tmp_path).write_text(json.dumps({"model": "opus"}))
        install.install(str(tmp_path), CMD, HUB, "coding", "tok")
        (settings_path(tmp_path).parent / "settings.local.json.courtyard-bak").unlink()
        (tmp_path / ".mcp.json").write_text(json.dumps({"mcpServers": {"courtyard": {}}}))
        install.uninstall(str(tmp_path))
        assert read(settings_path(tmp_path)) == {"model": "opus"}


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

    def test_the_wrapper_hands_claude_the_server_approval_as_one_argument(self, tmp_path):
        """Claude Code ignores the approval stored in settings.local.json outside a git
        checkout, so the launch carries it; the JSON must reach claude intact through the
        shell. A fake `claude` on PATH prints the arguments it received, one per line."""
        import os
        import subprocess

        install.install(str(tmp_path), CMD, HUB, "coding", "tok", model="haiku")
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        fake = bin_dir / "claude"
        fake.write_text('#!/bin/sh\nfor a in "$@"; do printf \'%s\\n\' "$a"; done\n')
        fake.chmod(0o755)
        run = subprocess.run(
            [str(tmp_path / "start-with-courtyard.sh"), "--extra"],
            env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"},
            capture_output=True,
            text=True,
            check=True,
        )
        argv = run.stdout.splitlines()
        assert argv[argv.index("--settings") + 1] == '{"enabledMcpjsonServers":["courtyard"]}'
        assert argv[argv.index("--model") + 1] == "haiku" and argv[-1] == "--extra"

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


class TestPiInstall:
    """Item 36 (D32): the pi adapter is one extension file plus the wrapper script."""

    def test_install_writes_the_extension_with_token_and_the_wrapper(self, tmp_path):
        result = install.install_pi(str(tmp_path), HUB, "pibot", "tok")
        ext = tmp_path / ".pi/extensions/courtyard.ts"
        assert result.path == str(ext)
        text = ext.read_text()
        assert '"tok"' in text and '"pibot"' in text and HUB in text
        assert "__COURTYARD_" not in text  # every placeholder substituted
        # the membership context's fallback (D40) is rendered in, without a team's name
        assert "You are configured as part of a team" in text and "of the team" not in text
        assert mode(ext) == 0o600
        script = tmp_path / "start-with-courtyard.sh"
        assert "exec pi " in script.read_text()
        assert mode(script) & 0o111
        skill = tmp_path / ".pi/skills/courtyard/SKILL.md"
        assert result.settings_path == str(skill)
        text2 = skill.read_text()
        assert text2.startswith("---\nname: courtyard")
        assert "courtyard_send" in text2 and "Written by the courtyard" in text2

    def test_the_wrapper_carries_the_declared_model(self, tmp_path):
        install.install_pi(str(tmp_path), HUB, "pibot", "tok", model="openai/gpt-5.6-luna")
        script = (tmp_path / "start-with-courtyard.sh").read_text()
        assert "exec pi --model openai/gpt-5.6-luna " in script

    def test_reinstall_regenerates_ours_and_backs_up_a_foreign_file(self, tmp_path):
        install.install_pi(str(tmp_path), HUB, "pibot", "tok")
        result = install.install_pi(str(tmp_path), HUB, "pibot", "tok2")
        assert result.replaced_server is True and result.backed_up is None
        assert '"tok2"' in (tmp_path / ".pi/extensions/courtyard.ts").read_text()
        theirs = tmp_path / ".pi/extensions/courtyard.ts"
        theirs.write_text("// my own extension\n")
        result = install.install_pi(str(tmp_path), HUB, "pibot", "tok3")
        backup = tmp_path / ".pi/extensions/courtyard.ts.courtyard-bak"
        assert result.backed_up == str(backup)
        assert backup.read_text() == "// my own extension\n"

    def test_uninstall_pi_reverses_exactly(self, tmp_path):
        install.install_pi(str(tmp_path), HUB, "pibot", "tok")
        result = install.uninstall_pi(str(tmp_path))
        assert result.removed_server is True and result.script_removed is True
        assert result.settings_cleaned is True  # the skill (rides the settings fields)
        assert not (tmp_path / ".pi/extensions/courtyard.ts").exists()
        assert not (tmp_path / "start-with-courtyard.sh").exists()
        assert not (tmp_path / ".pi/skills/courtyard").exists()
        with pytest.raises(NothingToUninstall):
            install.uninstall_pi(str(tmp_path))

    def test_uninstall_pi_restores_a_backed_up_foreign_extension(self, tmp_path):
        (tmp_path / ".pi/extensions").mkdir(parents=True)
        theirs = tmp_path / ".pi/extensions/courtyard.ts"
        theirs.write_text("// my own extension\n")
        install.install_pi(str(tmp_path), HUB, "pibot", "tok")
        result = install.uninstall_pi(str(tmp_path))
        assert result.restored_from_backup is True
        assert theirs.read_text() == "// my own extension\n"


class TestGitignore:
    """Item 28: registration's footprint stays out of git. Under a checkout the
    token-carrying names go into .gitignore (created if missing, appended in place,
    never duplicated); a plain directory is left alone; uninstall takes exactly our
    lines out again. The notice names what was written and what may be committed."""

    def test_a_checkout_gets_the_entries_and_the_notice_says_so(self, tmp_path):
        (tmp_path / ".git").mkdir()
        result = install.install(str(tmp_path), CMD, HUB, "coding", "tok")
        text = (tmp_path / ".gitignore").read_text()
        assert result.gitignore == str(tmp_path / ".gitignore")
        assert text.startswith(install.GITIGNORE_MARK + "\n")
        for entry in install.GITIGNORE_ENTRIES["claude-code"]:
            assert f"\n{entry}\n" in text
        assert "start-with-courtyard.sh" not in text  # committable on purpose
        assert "added them to .gitignore" in result.warning
        assert "may be committed" in result.warning

    def test_existing_lines_are_kept_and_ours_never_duplicated(self, tmp_path):
        (tmp_path / ".git").mkdir()
        (tmp_path / ".gitignore").write_text("node_modules/\n.mcp.json")  # no final newline
        first = install.install(str(tmp_path), CMD, HUB, "coding", "tok")
        again = install.install(str(tmp_path), CMD, HUB, "coding", "tok")
        text = (tmp_path / ".gitignore").read_text()
        assert text.startswith("node_modules/\n.mcp.json\n\n" + install.GITIGNORE_MARK)
        assert text.splitlines().count(".mcp.json") == 1  # the user's own line, once
        assert first.gitignore and again.gitignore is None
        assert ".gitignore already lists them" in again.warning

    def test_a_plain_directory_is_left_alone(self, tmp_path):
        result = install.install(str(tmp_path), CMD, HUB, "coding", "tok")
        assert not (tmp_path / ".gitignore").exists() and result.gitignore is None
        assert "not a git checkout" in result.warning

    def test_uninstall_takes_out_exactly_our_lines(self, tmp_path):
        (tmp_path / ".git").mkdir()
        (tmp_path / ".gitignore").write_text("dist/\n")
        install.install(str(tmp_path), CMD, HUB, "coding", "tok")
        undo = install.uninstall(str(tmp_path))
        assert undo.gitignore_cleaned is True
        assert (tmp_path / ".gitignore").read_text() == "dist/\n"
        # a file that held only our lines goes with them
        (tmp_path / ".gitignore").unlink()
        install.install(str(tmp_path), CMD, HUB, "coding", "tok")
        assert install.uninstall(str(tmp_path)).gitignore_cleaned is True
        assert not (tmp_path / ".gitignore").exists()

    def test_pi_lists_its_extension_and_keeps_the_skill_committable(self, tmp_path):
        (tmp_path / ".git").mkdir()
        result = install.install_pi(str(tmp_path), HUB, "pi-agent", "tok")
        text = (tmp_path / ".gitignore").read_text()
        assert ".pi/extensions/courtyard.ts\n" in text and "skills" not in text
        assert "may be committed" in result.warning
        assert install.uninstall_pi(str(tmp_path)).gitignore_cleaned is True
