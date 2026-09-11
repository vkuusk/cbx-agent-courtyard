"""The shift state machine and the settings API (design §8.1, D23).

Service-level tests drive ShiftService with a controllable clock and a fake spawner
against the real test database; API tests check the routes and error codes.
"""

from __future__ import annotations

import contextlib
import json
import os
import pty
import re
import signal
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from courtyard.common.models import BUILTIN_TERMINALS, Settings
from courtyard.hub.core import spawn
from courtyard.hub.core.errors import InvalidSetting, NoShiftToResume, ShiftBusy
from courtyard.hub.core.events import EventBus
from courtyard.hub.core.shift import SETTLE_SECONDS, ShiftService, launch_command
from courtyard.hub.core.spawn import (
    BUILTIN_SPAWNERS,
    Ghostty,
    _kill_tty,
    _tty_busy,
    _tty_pids,
    applescript_str,
    make_spawner,
    shell_command,
)
from courtyard.hub.storage.postgres import PostgresStorage

T0 = datetime(2026, 8, 25, 12, 0, 0, tzinfo=UTC)


class Clock:
    def __init__(self, now: datetime = T0):
        self.now = now

    def tick(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)

    def __call__(self) -> datetime:
        return self.now


class FakeSpawner:
    def __init__(self):
        self.spawned: list[tuple[str, str]] = []  # (cwd, command)
        self.closed: list[str] = []
        self.fail_for: set[str] = set()  # cwd substrings that refuse to spawn
        self.alive_refs: set[str] = set()  # windows whose session still runs (D25)

    def spawn(self, cwd: str, command: str) -> str:
        if any(marker in cwd for marker in self.fail_for):
            raise RuntimeError("no terminal for you")
        self.spawned.append((cwd, command))
        return f"ref-{len(self.spawned)}"

    def close(self, ref: str) -> bool:
        self.closed.append(ref)
        return True

    def alive(self, ref: str) -> bool:
        return ref in self.alive_refs


@pytest.fixture()
def storage(config):
    with psycopg.connect(config.database_url, autocommit=True) as conn:
        conn.execute("TRUNCATE agents, lines, messages, channels, lines_archive, settings CASCADE")
    s = PostgresStorage(config.database_url)
    s.open()
    yield s
    s.close()


def make_service(storage, clock, spawner, heartbeat=15.0, started_at=None):
    service = ShiftService(
        storage,
        EventBus(),
        heartbeat,
        clock=clock,
        spawner_factory=lambda app: spawner,
        hub_started_at=started_at or clock(),
    )

    # The app binds channels.begin_verification (D28, item 31); this stub keeps the
    # same contract: stored green flips to `unknown`, judging reopens for one
    # heartbeat interval + margin from "now".
    def verify() -> datetime:
        with storage.transaction() as uow:
            for agent in uow.agents.list():
                if agent.removed_at is None and agent.status in ("connected", "stale"):
                    uow.agents.set_status(agent.id, "unknown")
        return clock() + timedelta(seconds=heartbeat + 5.0)

    service.bind_verifier(verify)
    return service


def add_agent(storage, name, *, type="claude-code", workdir="/tmp/w", status="gone", model=None):
    with storage.transaction() as uow:
        agent = uow.agents.create(
            agent_id=uuid4(),
            name=name,
            type=type,
            description=None,
            sme_domain=None,
            workdir=workdir,
            token_hash=f"hash-{name}",
            token=f"token-{name}",
            launch=None,
            color=None,
            model=model,
        )
        if status != "invited":
            uow.agents.set_status(agent.id, status)
    return agent


class TestShiftMachine:
    def test_start_counts_down_one_heartbeat_window_then_spawns(self, storage):
        clock, spawner = Clock(), FakeSpawner()
        service = make_service(storage, clock, spawner)
        add_agent(storage, "coder")
        clock.tick(2)  # grace = one heartbeat (15) + margin (5) from pressing start
        status = service.start()
        assert status.state == "starting"
        assert status.grace_until == T0 + timedelta(seconds=22)
        assert spawner.spawned == []
        clock.tick(10)
        assert service.tick() is None  # still inside the grace window
        clock.tick(10)
        service.tick()
        assert len(spawner.spawned) == 1
        assert spawner.spawned[0][0] == "/tmp/w"

    def test_start_verifies_stored_green_and_spawns_the_dead(self, storage):
        """D28 (item 31): an agent whose session died with the last shift keeps its
        stored `connected` for up to gone_seconds. Start must not trust it — the
        status flips to `unknown`, and with no heartbeat during the grace the agent
        is spawned instead of skipped."""
        clock, spawner = Clock(), FakeSpawner()
        service = make_service(storage, clock, spawner, started_at=T0 - timedelta(hours=1))
        agent = add_agent(storage, "died-yesterday", status="connected")
        status = service.start()
        assert status.state == "starting"
        assert spawner.spawned == []  # even on an old hub, start is never instant now
        with storage.transaction() as uow:
            assert uow.agents.get(agent.id).status == "unknown"
        clock.tick(21)  # past heartbeat (15) + margin (5)
        service.tick()
        assert [cwd for cwd, _ in spawner.spawned] == ["/tmp/w"]

    def test_agents_that_prove_themselves_during_grace_are_not_spawned(self, storage):
        clock, spawner = Clock(), FakeSpawner()
        service = make_service(storage, clock, spawner, started_at=T0 - timedelta(hours=1))
        alive = add_agent(storage, "up-already", status="connected")
        add_agent(storage, "down", workdir="/tmp/down")
        service.start()
        with storage.transaction() as uow:
            uow.agents.set_status(alive.id, "connected")  # its heartbeat lands mid-grace
        clock.tick(21)
        service.tick()
        assert [cwd for cwd, _ in spawner.spawned] == ["/tmp/down"]

    def test_dummies_and_workdirless_agents_are_skipped(self, storage):
        clock, spawner = Clock(), FakeSpawner()
        service = make_service(storage, clock, spawner, started_at=T0 - timedelta(hours=1))
        add_agent(storage, "twin", type="dummy")
        add_agent(storage, "homeless", workdir=None)
        service.start()
        clock.tick(21)
        status = service.tick()
        assert spawner.spawned == []
        assert sorted(status.skipped) == ["homeless", "twin"]

    def test_settles_on_when_everyone_connects(self, storage):
        clock, spawner = Clock(), FakeSpawner()
        service = make_service(storage, clock, spawner, started_at=T0 - timedelta(hours=1))
        agent = add_agent(storage, "coder")
        service.start()
        clock.tick(21)
        service.tick()  # grace over -> spawn
        clock.tick(3)
        assert service.tick() is None  # spawned, still waiting
        with storage.transaction() as uow:
            uow.agents.set_status(agent.id, "connected")
        status = service.tick()
        assert status.state == "on"

    def test_settle_timeout_declares_on_with_stragglers(self, storage):
        clock, spawner = Clock(), FakeSpawner()
        service = make_service(storage, clock, spawner, started_at=T0 - timedelta(hours=1))
        add_agent(storage, "never-comes-up")
        service.start()
        clock.tick(21)
        service.tick()  # grace over -> spawn
        clock.tick(SETTLE_SECONDS + 1)
        status = service.tick()
        assert status.state == "on"

    def test_one_spawn_failure_does_not_stop_the_team(self, storage):
        clock, spawner = Clock(), FakeSpawner()
        spawner.fail_for.add("/tmp/broken")
        service = make_service(storage, clock, spawner, started_at=T0 - timedelta(hours=1))
        add_agent(storage, "broken", workdir="/tmp/broken")
        add_agent(storage, "fine", workdir="/tmp/fine")
        service.start()
        clock.tick(21)
        status = service.tick()
        assert [cwd for cwd, _ in spawner.spawned] == ["/tmp/fine"]
        assert status.skipped == ["broken"]

    def test_end_closes_exactly_what_was_spawned(self, storage):
        clock, spawner = Clock(), FakeSpawner()
        service = make_service(storage, clock, spawner, started_at=T0 - timedelta(hours=1))
        add_agent(storage, "coder")
        service.start()
        clock.tick(21)
        service.tick()
        status = service.end()
        assert status.state == "off"
        assert spawner.closed == ["ref-1"]

    def test_end_refuses_while_lines_are_mid_conversation(self, storage):
        clock, spawner = Clock(), FakeSpawner()
        service = make_service(storage, clock, spawner, started_at=T0 - timedelta(hours=1))
        a = add_agent(storage, "a")
        b = add_agent(storage, "b")
        service.start()
        clock.tick(21)
        service.tick()  # grace over -> spawn
        with storage.transaction() as uow:
            line = uow.lines.get_or_create_locked(a.id, b.id)
            msg = uow.messages.insert(
                message_id=uuid4(),
                line_id=line.id,
                sender=a.id,
                recipient=b.id,
                kind="message",
                body="hi",
                reply_to=None,
                status="queued",
            )
            uow.lines.set_turn(line.id, "awaiting_reply", b.id, msg.id)
        with pytest.raises(ShiftBusy):
            service.end()
        assert spawner.closed == []
        status = service.end(force=True)
        assert status.state == "off"
        assert spawner.closed == ["ref-1", "ref-2"]  # both agents' windows

    def test_start_is_idempotent_and_survives_a_hub_restart(self, storage):
        clock, spawner = Clock(), FakeSpawner()
        service = make_service(storage, clock, spawner, started_at=T0 - timedelta(hours=1))
        add_agent(storage, "coder")
        service.start()
        clock.tick(21)
        service.tick()  # grace over -> spawn
        service.start()  # pressing the button twice
        assert len(spawner.spawned) == 1
        # A new hub process mid-shift: the persisted document knows what was spawned.
        service2 = make_service(storage, clock, spawner, started_at=clock())
        assert service2.status().state == "starting"
        clock.tick(30)  # past the new grace — must NOT spawn coder a second time
        service2.tick()
        assert len(spawner.spawned) == 1
        status = service2.end(force=True)
        assert status.state == "off"
        assert spawner.closed == ["ref-1"]

    def test_launch_command_carries_the_model(self, storage):
        clock, spawner = Clock(), FakeSpawner()
        service = make_service(storage, clock, spawner, started_at=T0 - timedelta(hours=1))
        add_agent(storage, "coder", model="haiku")
        service.start()
        clock.tick(21)
        service.tick()
        assert spawner.spawned[0][1] == (
            "claude --dangerously-load-development-channels server:courtyard --model haiku"
        )

    def test_settings_reject_always_on(self, storage):
        service = make_service(storage, Clock(), FakeSpawner())
        with pytest.raises(InvalidSetting):
            service.update_settings({"team_mode": "always_on"})
        assert service.get_settings() == Settings()

    def test_settings_persist_across_service_restarts(self, storage):
        clock, spawner = Clock(), FakeSpawner()
        service = make_service(storage, clock, spawner)
        service.update_settings({"terminal_app": "iTerm2"})
        service2 = make_service(storage, clock, spawner)
        assert service2.get_settings().terminal_app == "iTerm2"


class TestEscaping:
    def test_applescript_string_escapes_quotes_and_backslashes(self):
        assert applescript_str('say "hi" \\ bye') == '"say \\"hi\\" \\\\ bye"'

    def test_shell_command_quotes_the_workdir(self):
        cmd = shell_command("/tmp/my agent's dir", "claude --flag")
        assert cmd == """cd '/tmp/my agent'"'"'s dir' && claude --flag"""


class TestTtyProbe:
    """Every spawner's liveness (`alive`) and its pre-close kill ride on the tty probe,
    so it is checked against a real pty with a real process on it. Regression, found
    live 2026-09-08: on the `pgrep -t`/`pkill -t` form both were silent no-ops on
    macOS 26 — D25 asked its abandoned-shift question with the windows open, and End
    shift closed windows while leaving the agents running."""

    @staticmethod
    def _sleeper_on_a_pty():
        """A `sleep` in its own session on a fresh pty — the shape a terminal window
        gives the agent's shell. The child reports its tty the way the Ghostty spawner
        has the real shell report it."""
        pid, master = pty.fork()
        if pid == 0:  # the child; execv never returns
            os.execv("/bin/sh", ["sh", "-c", "tty; sleep 300"])
        reported = ""
        while "\n" not in reported:
            reported += os.read(master, 128).decode(errors="replace")
        return pid, master, reported.strip()

    def test_it_finds_and_ends_the_processes_on_a_tty(self):
        pid, master, tty = self._sleeper_on_a_pty()
        name = tty.removeprefix("/dev/")
        try:
            assert pid in _tty_pids(name)
            assert _tty_busy(name) is True

            _kill_tty(tty)
            assert _tty_busy(name) is False  # end shift can now close a quiet window
        finally:
            with contextlib.suppress(OSError):
                os.kill(pid, signal.SIGKILL)
            with contextlib.suppress(ChildProcessError):
                os.waitpid(pid, 0)
            os.close(master)

    def test_a_tty_with_nothing_on_it_reads_idle(self):
        assert _tty_pids("ttys999") == [] and _tty_busy("ttys999") is False


#: one window id per built-in, in the type its dictionary declares (integer or text)
WINDOW_IDS = {"Terminal": "4711", "iTerm2": "17", "Ghostty": "tab-group-abc"}


class TestBuiltinSpawners:
    """The built-ins share one base (`OsascriptTerminal`): one ref shape, one liveness,
    one close sequence. Driving the real AppleScript is the manual runbook check (it
    needs the apps installed); these hold what every app must do the same way."""

    @staticmethod
    def ref(app, **fields):
        return json.dumps({"app": app, "window_id": WINDOW_IDS[app], **fields})

    def test_every_builtin_name_has_a_spawner(self):
        assert set(BUILTIN_SPAWNERS) == set(BUILTIN_TERMINALS)  # neither list drifts alone
        assert set(WINDOW_IDS) == set(BUILTIN_TERMINALS)
        for name, cls in BUILTIN_SPAWNERS.items():
            assert cls.name == name and isinstance(make_spawner(name), cls)

    def test_the_webui_reads_the_names_from_the_hub(self, client):
        # no hand-kept mirror in admin.js: the pulldown lists what the hub can drive
        assert client.get("/api/settings/terminals").json() == list(BUILTIN_TERMINALS)

    @pytest.mark.parametrize("app", BUILTIN_TERMINALS)
    def test_spawn_records_the_same_ref_shape(self, app, monkeypatch):
        spawner = make_spawner(app)
        monkeypatch.setattr(spawner, "_open", lambda cwd, command: ("w1", "/dev/ttys042"))
        ref = json.loads(spawner.spawn("/tmp/w", "claude"))
        assert ref == {"app": app, "window_id": "w1", "tty": "/dev/ttys042"}

    @pytest.mark.parametrize("app", BUILTIN_TERMINALS)
    def test_close_counts_the_window_then_kills_then_closes(self, app, monkeypatch):
        """The order is the whole design of the method: a window closing on a live
        process orphans the agent, and a count taken after the kill can read zero because
        ending the shell already retired the window (Ghostty always; Terminal under a
        close-on-exit profile)."""
        spawner = make_spawner(app)
        order = []
        monkeypatch.setattr(spawn, "_kill_tty", lambda tty: order.append(f"kill {tty}"))

        def fake_osascript(script):
            if script == f"return {spawner.app} is running":
                order.append("running?")  # asked OUTSIDE a tell block: never launches
                return "true"
            assert script.startswith(f"tell {spawner.app}")
            # the id is compared in its own type: quoted text, or a bare integer
            literal = f'"{WINDOW_IDS[app]}"' if spawner.text_ids else WINDOW_IDS[app]
            assert f"every window whose id is {literal}" in script
            if "count of" in script:
                order.append("count")
                return "1"
            order.append("close")
            assert f"    {spawner.close_verb}\n" in script
            return ""

        monkeypatch.setattr(spawn, "_osascript", fake_osascript)
        assert spawner.close(self.ref(app, tty="/dev/ttys042")) is True
        assert order == ["running?", "count", "kill /dev/ttys042", "close"]

    @pytest.mark.parametrize("app", BUILTIN_TERMINALS)
    def test_close_leaves_a_reused_tty_alone_when_the_window_is_gone(self, app, monkeypatch):
        """A freed tty name goes to the next window that opens, so once the agent's window
        is gone, whatever runs on its tty is somebody else's: the operator's own shell,
        an editor, a `make run`. The gone count ends the close before any signal."""
        signalled, scripts = [], []
        monkeypatch.setattr(spawn, "_kill_tty", lambda tty: signalled.append(tty))

        def fake_osascript(script):
            scripts.append(script)
            return "true" if "is running" in script else "0"

        monkeypatch.setattr(spawn, "_osascript", fake_osascript)
        assert make_spawner(app).close(self.ref(app, tty="/dev/ttys042")) is False
        assert signalled == [] and not any("close" in s for s in scripts)

    @pytest.mark.parametrize("app", BUILTIN_TERMINALS)
    def test_a_quit_app_is_not_launched_by_close_or_alive(self, app, monkeypatch):
        monkeypatch.setattr(spawn, "_kill_tty", lambda tty: pytest.fail("must not signal"))
        monkeypatch.setattr(spawn, "_tty_busy", lambda name: True)
        tells = []

        def fake_osascript(script):
            if script.startswith("tell"):
                tells.append(script)  # a tell block launches a quit app
            return "false"

        monkeypatch.setattr(spawn, "_osascript", fake_osascript)
        spawner = make_spawner(app)
        assert spawner.close(self.ref(app, tty="/dev/ttys042")) is False
        assert spawner.alive(self.ref(app, tty="/dev/ttys042")) is False
        assert tells == []

    @pytest.mark.parametrize("app", BUILTIN_TERMINALS)
    def test_alive_needs_the_window_as_well_as_a_busy_tty(self, app, monkeypatch):
        """Resume respawns the dead and the stale-shift question waits on the living, so
        liveness must not mistake a stranger on a reused tty for the agent (D25)."""
        monkeypatch.setattr(spawn, "_tty_busy", lambda name: True)
        answers = {"is running": "true", "count of": "0"}
        monkeypatch.setattr(
            spawn, "_osascript", lambda script: next(v for k, v in answers.items() if k in script)
        )
        spawner = make_spawner(app)
        assert spawner.alive(self.ref(app, tty="/dev/ttys042")) is False
        answers["count of"] = "1"
        assert spawner.alive(self.ref(app, tty="/dev/ttys042")) is True
        monkeypatch.setattr(
            spawn, "_tty_busy", lambda name: False
        )  # an idle tty: dead, no osascript
        monkeypatch.setattr(spawn, "_osascript", lambda script: pytest.fail("no need to ask"))
        assert spawner.alive(self.ref(app, tty="/dev/ttys042")) is False

    @pytest.mark.parametrize("app", BUILTIN_TERMINALS)
    def test_close_survives_an_app_that_refuses(self, app, monkeypatch):
        def refuse(script):
            raise spawn.SpawnFailed("not running")

        monkeypatch.setattr(spawn, "_osascript", refuse)
        assert make_spawner(app).close(self.ref(app, tty="")) is False

    def test_a_ref_without_a_tty_reads_dead(self):
        # honest degradation: liveness cannot verify a window whose tty is unknown
        for app in BUILTIN_TERMINALS:
            assert make_spawner(app).alive(self.ref(app, tty="")) is False
        assert make_spawner("Terminal").alive("not json") is False

    def test_iterm2_is_addressed_by_bundle_id(self):
        # `application "iTerm2"` does not resolve (the app file is iTerm.app)
        assert 'application id "com.googlecode.iterm2"' == make_spawner("iTerm2").app


class TestGhosttySpawner:
    """D33: Ghostty is a third fully driven terminal — it opens AND closes windows.
    What is Ghostty's alone: the line is typed as `initial input`, and the shell reports
    its tty through a temp file because the dictionary exposes none."""

    def ref(self, **fields):
        return json.dumps({"app": "Ghostty", "window_id": "tab-group-abc", **fields})

    def test_spawn_types_the_line_and_reads_back_the_reported_tty(self, monkeypatch):
        seen = {}

        def fake_osascript(script):
            seen["script"] = script
            # stand in for the spawned shell: report the tty into the file it was given
            seen["ttyfile"] = re.search(r"tty > (\S+);", script).group(1)
            Path(seen["ttyfile"]).write_text("/dev/ttys042\n")
            return "tab-group-abc"

        monkeypatch.setattr(spawn, "_osascript", fake_osascript)
        ref = json.loads(Ghostty().spawn("/tmp/my agent's dir", "claude --model sonnet"))

        assert ref == {"app": "Ghostty", "window_id": "tab-group-abc", "tty": "/dev/ttys042"}
        script = seen["script"]
        assert "new surface configuration" in script
        assert """set initial working directory of cfg to "/tmp/my agent's dir\"""" in script
        # the shell line rides through BOTH escapers: shlex for the shell, then the
        # AppleScript literal (whose backslash-quote is what reaches the typed input)
        assert """cd '/tmp/my agent'\\"'\\"'s dir' && claude --model sonnet""" in script
        assert "& linefeed" in script  # the typed line runs only once the shell reads a return
        assert "set command of cfg" not in script  # the login shell must outlive the agent
        assert not Path(seen["ttyfile"]).exists()  # the temp file does not survive the spawn

    def test_a_shell_that_never_reports_its_tty_still_yields_a_window_ref(self, monkeypatch):
        monkeypatch.setattr(spawn, "TTY_REPORT_TIMEOUT", 0.2)
        monkeypatch.setattr(spawn, "_osascript", lambda script: "tab-group-abc")
        ref = json.loads(Ghostty().spawn("/tmp/w", "claude"))
        # honest degradation: the window is recorded, but liveness cannot verify it
        assert ref["window_id"] == "tab-group-abc" and ref["tty"] == ""
        assert Ghostty().alive(json.dumps(ref)) is False

    def test_the_setting_accepts_it_and_no_custom_app_may_shadow_it(self, client):
        assert client.patch("/api/settings", json={"terminal_app": "Ghostty"}).status_code == 200
        resp = client.patch(
            "/api/settings",
            json={"custom_terminals": [{"name": "Ghostty", "command": "x {command}"}]},
        )
        assert resp.status_code == 422 and resp.json()["error"]["code"] == "invalid_setting"
        assert client.patch("/api/settings", json={"terminal_app": "Terminal"}).status_code == 200


def make_stale(storage, clock, spawner, names=("coder",)):
    """Drive a shift to the abandoned state (D25): started long ago, settle timed out,
    every agent gone, every window dead (FakeSpawner reports dead unless told alive)."""
    service = make_service(storage, clock, spawner, started_at=T0 - timedelta(hours=1))
    for name in names:
        add_agent(storage, name, workdir=f"/tmp/{name}")
    service.start()
    clock.tick(21)
    service.tick()  # verification grace over -> spawn
    clock.tick(SETTLE_SECONDS + 1)
    service.tick()  # settle timeout -> on
    return service


def awaiting_line(storage, a, b):
    with storage.transaction() as uow:
        line = uow.lines.get_or_create_locked(a.id, b.id)
        msg = uow.messages.insert(
            message_id=uuid4(),
            line_id=line.id,
            sender=a.id,
            recipient=b.id,
            kind="message",
            body="hi",
            reply_to=None,
            status="delivered",
        )
        uow.lines.set_turn(line.id, "awaiting_reply", b.id, msg.id)
    return line, msg


class TestStaleShift:
    def test_abandoned_shift_reads_stale(self, storage):
        clock, spawner = Clock(), FakeSpawner()
        service = make_stale(storage, clock, spawner)
        status = service.status()
        assert status.state == "on" and status.stale

    def test_not_stale_while_a_spawned_window_is_alive(self, storage):
        clock, spawner = Clock(), FakeSpawner()
        service = make_stale(storage, clock, spawner)
        spawner.alive_refs.add("ref-1")  # the window sits open (first-run dialog, say)
        assert not service.status().stale

    def test_not_stale_while_anyone_is_connected(self, storage):
        clock, spawner = Clock(), FakeSpawner()
        service = make_stale(storage, clock, spawner)
        with storage.transaction() as uow:
            agent = uow.agents.get_by_name("coder")
            uow.agents.set_status(agent.id, "connected")
        assert not service.status().stale

    def test_not_stale_on_a_young_hub(self, storage):
        """A hub restart mid-shift must never raise the question: live agents look down
        only until their next heartbeat, inside the grace window."""
        clock, spawner = Clock(), FakeSpawner()
        make_stale(storage, clock, spawner)
        service2 = make_service(storage, clock, spawner, started_at=clock())
        assert not service2.status().stale
        clock.tick(21)  # past heartbeat (15) + margin (5)
        assert service2.status().stale

    def test_resume_respawns_only_the_dead_windows_and_keeps_the_books(self, storage):
        clock, spawner = Clock(), FakeSpawner()
        service = make_stale(storage, clock, spawner, names=("alpha", "beta"))
        with storage.transaction() as uow:
            alpha = uow.agents.get_by_name("alpha")
            beta = uow.agents.get_by_name("beta")
        line, msg = awaiting_line(storage, alpha, beta)
        started_before = service.status().started_at
        spawner.alive_refs.add("ref-1")  # alpha's window survived; beta's is gone

        status = service.resume()

        assert status.state == "starting" and status.started_at == started_before
        assert len(spawner.spawned) == 3  # alpha, beta, then beta again — never alpha twice
        assert spawner.spawned[2][0] == "/tmp/beta"
        assert sorted(s.agent_name for s in status.spawns) == ["alpha", "beta"]
        with storage.transaction() as uow:
            assert uow.lines.get(line.id).state == "awaiting_reply"  # books untouched
            assert uow.messages.get(msg.id).status == "delivered"  # nothing expired

    def test_resume_mid_shift_starts_only_the_missing_agent(self, storage):
        """The architect's rule (D25 amendment): with 1 of 2 healthy, resume by starting
        the second — the connected agent is untouched, its dead spawn record is simply
        retired, and the books never move."""
        clock, spawner = Clock(), FakeSpawner()
        service = make_stale(storage, clock, spawner, names=("alpha", "beta"))
        with storage.transaction() as uow:
            alpha = uow.agents.get_by_name("alpha")
            uow.agents.set_status(alpha.id, "connected")  # alpha lives (own terminal)
        assert not service.status().stale  # someone is home: no question

        status = service.resume()

        assert len(spawner.spawned) == 3  # alpha, beta, then ONLY beta again
        assert spawner.spawned[2][0] == "/tmp/beta"
        assert [s.agent_name for s in status.spawns] == ["beta"]

    def test_resume_with_no_shift_open_is_refused(self, storage):
        service = make_service(storage, Clock(), FakeSpawner())
        with pytest.raises(NoShiftToResume):
            service.resume()

    def test_start_on_a_stale_shift_closes_the_books_then_starts_fresh(self, storage):
        clock, spawner = Clock(), FakeSpawner()
        service = make_stale(storage, clock, spawner, names=("alpha", "beta"))
        with storage.transaction() as uow:
            alpha = uow.agents.get_by_name("alpha")
            beta = uow.agents.get_by_name("beta")
        line, msg = awaiting_line(storage, alpha, beta)
        started_before = service.status().started_at

        status = service.start()

        assert spawner.closed == ["ref-1", "ref-2"]  # the old shift's windows
        assert status.state == "starting" and status.started_at != started_before
        clock.tick(21)
        service.tick()  # verification grace over -> spawn
        assert len(spawner.spawned) == 4  # a fresh spawn per agent
        with storage.transaction() as uow:
            assert uow.lines.get(line.id).state == "idle"  # books closed (D24)
            assert uow.messages.get(msg.id).status == "expired"

    def test_start_on_a_running_shift_stays_idempotent(self, storage):
        clock, spawner = Clock(), FakeSpawner()
        service = make_stale(storage, clock, spawner)
        with storage.transaction() as uow:
            agent = uow.agents.get_by_name("coder")
            uow.agents.set_status(agent.id, "connected")  # somebody IS home: not stale
        started_before = service.status().started_at
        status = service.start()
        assert status.started_at == started_before
        assert len(spawner.spawned) == 1  # nothing new

    def test_checking_window_reported_while_the_hub_is_young(self, storage):
        """D26: a hub restarted into a running shift reports checking_until (the UI shows
        the countdown, not unverified statuses); when it passes, stale can appear —
        one transition, never green-then-broken-then-question."""
        clock, spawner = Clock(), FakeSpawner()
        service = make_stale(storage, clock, spawner)
        assert service.status().checking_until is None  # old hub: nothing to verify

        service2 = make_service(storage, clock, spawner, started_at=clock())
        status = service2.status()
        assert status.checking_until is not None
        assert not status.stale  # no claims while checking
        clock.tick(21)
        status = service2.status()
        assert status.checking_until is None and status.stale

    def test_tick_publishes_the_stale_transition_once(self, storage):
        clock, spawner = Clock(), FakeSpawner()
        service = make_stale(storage, clock, spawner)
        first = service.tick()
        assert first is not None and first.stale
        assert service.tick() is None  # no change, no event


class TestShiftApi:
    def test_status_start_end_round_trip(self, client):
        assert client.get("/api/shift").json()["state"] == "off"
        # No claude-code agents registered: start spawns nothing and settles by liveness
        # (all zero targets connected) on the next tick — state is at least `starting`.
        resp = client.post("/api/shift/start")
        assert resp.status_code == 200
        assert resp.json()["state"] in ("starting", "on")
        resp = client.post("/api/shift/end", json={"force": False})
        assert resp.status_code == 200
        assert resp.json()["state"] == "off"

    def test_resume_with_no_shift_is_a_409(self, client):
        resp = client.post("/api/shift/resume")
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "no_shift"

    def test_settings_round_trip_and_validation(self, client):
        assert client.get("/api/settings").json() == {
            "team_mode": "on_shift",
            "terminal_app": "Terminal",
            "custom_terminals": [],
            "default_line_mode": "supervised",
            "discovery": "auto",
            "thread_budget": 12,
            "recall_limit": 5,
            "recall_trim_chars": 600,
        }
        resp = client.patch("/api/settings", json={"terminal_app": "iTerm2"})
        assert resp.status_code == 200
        assert resp.json()["terminal_app"] == "iTerm2"
        resp = client.patch("/api/settings", json={"default_line_mode": "auto_pass"})
        assert resp.status_code == 200
        assert resp.json()["default_line_mode"] == "auto_pass"
        resp = client.patch("/api/settings", json={"discovery": "manual"})
        assert resp.status_code == 200
        assert resp.json()["discovery"] == "manual"
        assert client.patch("/api/settings", json={"discovery": "open"}).status_code == 422
        client.patch("/api/settings", json={"discovery": "auto"})
        resp = client.patch("/api/settings", json={"terminal_app": "xterm"})
        assert resp.status_code == 422  # not defined (item 20: definable under custom terminals)
        assert client.patch("/api/settings", json={"default_line_mode": "yolo"}).status_code == 422
        resp = client.patch("/api/settings", json={"team_mode": "always_on"})
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "invalid_setting"


def test_launch_command_without_model():
    from courtyard.common.models import Agent

    agent = Agent.model_construct(type="claude-code", model=None)
    assert launch_command(agent) == (
        "claude --dangerously-load-development-channels server:courtyard"
    )


class TestCustomTerminals:
    """Item 20: operator-defined terminal applications (name + start string)."""

    def test_add_select_edit_and_the_refusals(self, client):
        resp = client.patch(
            "/api/settings",
            json={"custom_terminals": [{"name": "kitty", "command": "kitty {command}"}]},
        )
        assert resp.status_code == 200
        resp = client.patch("/api/settings", json={"terminal_app": "kitty"})
        assert resp.status_code == 200 and resp.json()["terminal_app"] == "kitty"

        for label, patch in (
            ("unknown app", {"terminal_app": "ghostty"}),
            ("no {command}", {"custom_terminals": [{"name": "kitty", "command": "kitty"}]}),
            (
                "shadows a built-in",
                {"custom_terminals": [{"name": "Terminal", "command": "x {command}"}]},
            ),
            ("removing the selected app", {"custom_terminals": []}),
            (
                "duplicate names",
                {
                    "custom_terminals": [
                        {"name": "kitty", "command": "a {command}"},
                        {"name": "kitty", "command": "b {command}"},
                    ]
                },
            ),
        ):
            resp = client.patch("/api/settings", json=patch)
            assert resp.status_code == 422, label
            assert resp.json()["error"]["code"] == "invalid_setting", label

        # back to a built-in, then the custom can go
        assert client.patch("/api/settings", json={"terminal_app": "Terminal"}).status_code == 200
        assert client.patch("/api/settings", json={"custom_terminals": []}).status_code == 200

    def test_template_rendering_quotes_both_holes(self):
        from courtyard.hub.core.spawn import CommandTemplate, make_spawner, render_template

        rendered = render_template(
            "kitty --directory {dir} sh -c {command}", "/tmp/my dir", "claude --x"
        )
        assert rendered.startswith("kitty --directory '/tmp/my dir' sh -c ")
        assert "claude --x" in rendered  # {command} = ONE quoted token (cd + launch)
        spawner = make_spawner("kitty", {"kitty": "kitty {command}"})
        assert isinstance(spawner, CommandTemplate)
        assert spawner.close("anything") is False and spawner.alive("x") is False


def test_launch_command_per_type():
    from courtyard.common.models import Agent

    assert launch_command(Agent.model_construct(type="pi", model=None)) == "pi"
    assert "claude --dangerously" in launch_command(
        Agent.model_construct(type="claude-code", model=None)
    )
