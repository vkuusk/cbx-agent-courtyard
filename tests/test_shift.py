"""The shift state machine and the settings API (design §8.1, D23).

Service-level tests drive ShiftService with a controllable clock and a fake spawner
against the real test database; API tests check the routes and error codes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest

from courtyard.common.models import Settings
from courtyard.hub.core.errors import InvalidSetting, NoShiftToResume, ShiftBusy
from courtyard.hub.core.events import EventBus
from courtyard.hub.core.shift import SETTLE_SECONDS, ShiftService, launch_command
from courtyard.hub.core.spawn import applescript_str, shell_command
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
    return ShiftService(
        storage,
        EventBus(),
        heartbeat,
        clock=clock,
        spawner_factory=lambda app: spawner,
        hub_started_at=started_at or clock(),
    )


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
    def test_start_on_a_young_hub_counts_down_then_spawns(self, storage):
        clock, spawner = Clock(), FakeSpawner()
        service = make_service(storage, clock, spawner)  # hub started at T0
        add_agent(storage, "coder")
        clock.tick(2)  # the hub is 2 s old; grace = 15 + 5 = 20 s
        status = service.start()
        assert status.state == "starting"
        assert status.grace_until == T0 + timedelta(seconds=20)
        assert spawner.spawned == []
        clock.tick(10)
        assert service.tick() is None  # still inside the grace window
        clock.tick(10)
        service.tick()
        assert len(spawner.spawned) == 1
        assert spawner.spawned[0][0] == "/tmp/w"

    def test_start_on_an_old_hub_spawns_immediately(self, storage):
        clock, spawner = Clock(), FakeSpawner()
        service = make_service(storage, clock, spawner, started_at=T0 - timedelta(hours=1))
        add_agent(storage, "coder")
        status = service.start()
        assert status.state == "starting"
        assert len(spawner.spawned) == 1

    def test_connected_agents_are_not_spawned(self, storage):
        clock, spawner = Clock(), FakeSpawner()
        service = make_service(storage, clock, spawner, started_at=T0 - timedelta(hours=1))
        add_agent(storage, "up-already", status="connected")
        add_agent(storage, "down", workdir="/tmp/down")
        service.start()
        assert [cwd for cwd, _ in spawner.spawned] == ["/tmp/down"]

    def test_puppets_and_workdirless_agents_are_skipped(self, storage):
        clock, spawner = Clock(), FakeSpawner()
        service = make_service(storage, clock, spawner, started_at=T0 - timedelta(hours=1))
        add_agent(storage, "twin", type="puppet")
        add_agent(storage, "homeless", workdir=None)
        status = service.start()
        assert spawner.spawned == []
        assert sorted(status.skipped) == ["homeless", "twin"]

    def test_settles_on_when_everyone_connects(self, storage):
        clock, spawner = Clock(), FakeSpawner()
        service = make_service(storage, clock, spawner, started_at=T0 - timedelta(hours=1))
        agent = add_agent(storage, "coder")
        service.start()
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
        clock.tick(SETTLE_SECONDS + 1)
        status = service.tick()
        assert status.state == "on"

    def test_one_spawn_failure_does_not_stop_the_team(self, storage):
        clock, spawner = Clock(), FakeSpawner()
        spawner.fail_for.add("/tmp/broken")
        service = make_service(storage, clock, spawner, started_at=T0 - timedelta(hours=1))
        add_agent(storage, "broken", workdir="/tmp/broken")
        add_agent(storage, "fine", workdir="/tmp/fine")
        status = service.start()
        assert [cwd for cwd, _ in spawner.spawned] == ["/tmp/fine"]
        assert status.skipped == ["broken"]

    def test_end_closes_exactly_what_was_spawned(self, storage):
        clock, spawner = Clock(), FakeSpawner()
        service = make_service(storage, clock, spawner, started_at=T0 - timedelta(hours=1))
        add_agent(storage, "coder")
        service.start()
        status = service.end()
        assert status.state == "off"
        assert spawner.closed == ["ref-1"]

    def test_end_refuses_while_lines_are_mid_conversation(self, storage):
        clock, spawner = Clock(), FakeSpawner()
        service = make_service(storage, clock, spawner, started_at=T0 - timedelta(hours=1))
        a = add_agent(storage, "a")
        b = add_agent(storage, "b")
        service.start()
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


def make_stale(storage, clock, spawner, names=("coder",)):
    """Drive a shift to the abandoned state (D25): started long ago, settle timed out,
    every agent gone, every window dead (FakeSpawner reports dead unless told alive)."""
    service = make_service(storage, clock, spawner, started_at=T0 - timedelta(hours=1))
    for name in names:
        add_agent(storage, name, workdir=f"/tmp/{name}")
    service.start()
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
        }
        resp = client.patch("/api/settings", json={"terminal_app": "iTerm2"})
        assert resp.status_code == 200
        assert resp.json()["terminal_app"] == "iTerm2"
        resp = client.patch("/api/settings", json={"default_line_mode": "auto_pass"})
        assert resp.status_code == 200
        assert resp.json()["default_line_mode"] == "auto_pass"
        resp = client.patch("/api/settings", json={"terminal_app": "xterm"})
        assert resp.status_code == 422  # not defined (item 20: definable under custom terminals)
        assert client.patch("/api/settings", json={"default_line_mode": "yolo"}).status_code == 422
        resp = client.patch("/api/settings", json={"team_mode": "always_on"})
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "invalid_setting"


def test_launch_command_without_model():
    from courtyard.common.models import Agent

    agent = Agent.model_construct(model=None)
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
