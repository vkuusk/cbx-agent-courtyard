"""The Shift (design §8.1, D23): one operator gesture that starts every registered agent
not already up, and ends by closing exactly what it started.

State machine: off -> starting (verification grace, then spawn) -> on -> off. The grace
window exists because stored liveness is a claim, not a fact (D28, item 31): an agent
whose session died with the last shift keeps its stored green for up to `gone_seconds`,
and after a hub restart a healthy agent looks down until its adapter's next heartbeat
re-attaches — spawning on either claim gets it wrong (a skipped dead agent, or a second
session on a living identity). So start hands liveness back to the channel layer
(`begin_verification`: stored green flips to `unknown`) and waits one heartbeat
interval (+ margin): agents that prove themselves with a beat are skipped, whatever
stays unproven is spawned.

The hub spawns fire-and-forget (§8): no PTY, no supervision, no restarts. It records one
thing per spawn — the terminal window reference — so End shift knows what is its to
close. Liveness stays the only health signal.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from courtyard.common.models import BUILTIN_TERMINALS, Agent, Settings, ShiftStatus
from courtyard.hub.core.board import expire_open_work
from courtyard.hub.core.errors import InvalidSetting, NoShiftToResume, ShiftBusy
from courtyard.hub.core.events import EventBus
from courtyard.hub.core.spawn import TerminalSpawner, make_spawner
from courtyard.hub.storage.repo import Storage

logger = logging.getLogger("courtyard.hub")

GRACE_MARGIN_SECONDS = 5.0  # heartbeat + this = how old the hub must be to judge liveness
SETTLE_SECONDS = 60.0  # after spawning, how long to wait for everyone before declaring on

SETTINGS_KEY = "courtyard"  # the operator-changeable settings document
SHIFT_KEY = "shift"  # the shift state document (survives hub restarts)

# The launch command for a claude-code agent. Channels are a research preview and the
# flag contract has drifted before (feedback item 11) — this is the 2.1.245-verified
# form; `make test-comms` proves it after any Claude Code auto-update.
CLAUDE_LAUNCH = "claude --dangerously-load-development-channels server:courtyard"


def launch_command_text(model: str | None) -> str:
    return CLAUDE_LAUNCH + (f" --model {model}" if model else "")


def launch_command(agent: Agent) -> str:
    """Per-type launch recipe (§8.1's seam). pi needs no flag: the courtyard
    extension is auto-discovered from `.pi/extensions/` (item 36, D32)."""
    if agent.type == "pi":
        return "pi"
    return launch_command_text(agent.model)


def _now() -> datetime:
    return datetime.now(UTC)


class ShiftService:
    """Owns the shift state machine and the operator-changeable settings.

    Thread-safe: API routes run in FastAPI's threadpool while tick() runs on its own
    cadence. The persisted documents are the truth across restarts; the in-memory copies
    exist so a 1 s tick does not hit the database."""

    def __init__(
        self,
        storage: Storage,
        events: EventBus,
        heartbeat_seconds: float,
        clock: Callable[[], datetime] = _now,
        spawner_factory: Callable[[str], TerminalSpawner] | None = None,
        hub_started_at: datetime | None = None,
    ):
        self._storage = storage
        self._events = events
        self._heartbeat = heartbeat_seconds
        self._clock = clock
        # The default factory resolves custom terminal apps (item 20) against the
        # CURRENT settings, so an edited start string applies from the next spawn.
        self._make_spawner = spawner_factory or (
            lambda app: make_spawner(
                app, {t.name: t.command for t in self._settings.custom_terminals}
            )
        )
        self._hub_started_at = hub_started_at or clock()
        # D28 (item 31): channels.begin_verification, bound by the app once both
        # services exist (channels itself needs this service's settings for discovery).
        self._verifier: Callable[[], datetime] | None = None
        self._lock = threading.Lock()
        # tick() publishes only transitions of the derived flags (D25 stale, D26 checking)
        self._last_on_signature: tuple[bool, bool] | None = None
        with storage.transaction() as uow:
            self._settings = Settings.model_validate(uow.settings.get(SETTINGS_KEY) or {})
            self._doc: dict[str, Any] = uow.settings.get(SHIFT_KEY) or {"state": "off"}
        # A restart mid-grace re-judges against the new hub start; spawns already made
        # are in the document and are never spawned twice.
        if self._doc.get("state") == "starting" and not self._doc.get("spawned"):
            self._doc["grace_until"] = self._judge_after().isoformat()

    # -- settings ---------------------------------------------------------------------

    def get_settings(self) -> Settings:
        with self._lock:
            return self._settings

    def update_settings(self, patch: dict[str, Any]) -> Settings:
        if patch.get("team_mode") == "always_on":
            raise InvalidSetting("team mode 'always_on' is not available in v1")
        with self._lock:
            merged = self._settings.model_copy(update=patch)
            merged = Settings.model_validate(merged.model_dump())  # re-check literals
            self._check_terminals(merged)
            with self._storage.transaction() as uow:
                uow.settings.set(SETTINGS_KEY, merged.model_dump())
            self._settings = merged
            return merged

    @staticmethod
    def _check_terminals(settings: Settings) -> None:
        """Item 20: custom terminal apps are operator-defined start strings. Names must
        not shadow the built-ins or each other; every start string must place the launch
        `{command}` somewhere; the selected app must actually exist."""
        names = [t.name.strip() for t in settings.custom_terminals]
        for terminal, name in zip(settings.custom_terminals, names, strict=True):
            if not name:
                raise InvalidSetting("a custom terminal needs a name")
            if name in BUILTIN_TERMINALS:
                raise InvalidSetting(f"{name!r} is a built-in terminal application")
            if "{command}" not in terminal.command:
                raise InvalidSetting(
                    f"{name!r}: the start string must contain {{command}} — where the "
                    "agent's launch command goes ({dir} is optional)"
                )
        if len(set(names)) != len(names):
            raise InvalidSetting("custom terminal names must be unique")
        if settings.terminal_app not in BUILTIN_TERMINALS and settings.terminal_app not in names:
            raise InvalidSetting(
                f"terminal application {settings.terminal_app!r} is not defined — "
                "pick a built-in or add it under custom terminals first"
            )

    # -- the shift --------------------------------------------------------------------

    def bind_verifier(self, verifier: Callable[[], datetime]) -> None:
        """D28 (item 31): the liveness layer's `begin_verification` — flips stored
        green to `unknown` and reopens judging; returns when judging begins."""
        self._verifier = verifier

    def status(self) -> ShiftStatus:
        with self._lock:
            return self._status()

    def start(self) -> ShiftStatus:
        """Idempotent while a shift is genuinely running. On a STALE shift (D25 — left
        open, nobody home) this is the "start a new shift" answer: close yesterday's
        books first, then begin fresh."""
        expired_lines: list = []
        board_events: list = []
        with self._lock:
            if self._doc.get("state") != "off":
                if not self._stale():
                    return self._status()
                expired_lines, board_events = self._end_locked(force=True)
            now = self._clock()
            # D28 (item 31): stored liveness may be the dead last shift's claim — ask
            # the liveness layer to flip green to `unknown` and reopen judging; the
            # grace runs until its verdict, so a dead agent that still *reads*
            # connected is spawned, not skipped. Unbound (service-level tests), the
            # hub-age grace alone remains.
            if self._verifier is not None:
                grace_until = self._verifier()
            else:
                grace_until = max(now, self._judge_after())
            self._doc = {
                "state": "starting",
                "started_at": now.isoformat(),
                "grace_until": grace_until.isoformat(),
                "terminal_app": self._settings.terminal_app,
                "spawned": False,
                "spawns": [],
                "skipped": [],
            }
            self._persist()
            logger.info("shift: starting (grace until %s)", self._doc["grace_until"])
            status = self._status()
        self._publish_board(board_events, expired_lines)
        self._publish(status)
        return self.tick() or status

    def resume(self) -> ShiftStatus:
        """D25's "resume shift": bring the abandoned shift's team back up. Spawn records
        whose window is dead are dropped and respawned; a window still alive (waiting on
        a first-run dialog, say) is left alone — never doubled. The books stay open:
        unfinished conversations continue, re-attach redelivery (§6.4) does the rest."""
        with self._lock:
            if self._doc.get("state") == "off":
                raise NoShiftToResume("no shift is open — press Start shift instead")
            now = self._clock()
            spawner = self._make_spawner(self._doc.get("terminal_app", "Terminal"))
            alive_spawns = []
            dead: list[str] = []
            for spawn in self._doc.get("spawns", []):
                ref = spawn.get("window_ref")
                try:
                    alive = bool(ref) and spawner.alive(ref)
                except Exception:  # noqa: BLE001 - an unverifiable window counts as dead
                    alive = False
                if alive:
                    alive_spawns.append(spawn)
                else:
                    dead.append(spawn["agent_name"])
            self._doc["spawns"] = alive_spawns
            self._doc["state"] = "starting"
            logger.info(
                "shift: resuming (windows still alive: %s; respawning: %s)",
                [s["agent_name"] for s in alive_spawns] or "-",
                dead or "-",
            )
            self._spawn_missing(now)  # spawns every target not connected and not alive
            status = self._status()
        self._publish(status)
        return self.tick() or status

    def end(self, force: bool = False) -> ShiftStatus:
        """Close what the shift opened; refuse (without force) while lines are mid-work."""
        with self._lock:
            if self._doc.get("state") == "off":
                return self._status()
            expired_lines, board_events = self._end_locked(force)
            status = self._status()
        self._publish_board(board_events, expired_lines)
        self._publish(status)
        return status

    def _end_locked(self, force: bool) -> tuple[list, list]:
        """The end-of-shift work, caller holding the lock: close the recorded windows,
        close the books (D24), persist `off`. Returns (expired lines, board events)."""
        if not force:
            busy = self._busy_lines()
            if busy:
                raise ShiftBusy(
                    f"{busy} line{'s are' if busy != 1 else ' is'} mid-conversation",
                    busy_lines=busy,
                )
        spawner = self._make_spawner(self._doc.get("terminal_app", "Terminal"))
        closed: list[str] = []
        failed: list[str] = []
        for spawn in self._doc.get("spawns", []):
            if not spawn.get("window_ref"):
                continue
            try:
                ok = spawner.close(spawn["window_ref"])
            except Exception:  # noqa: BLE001 - a vanished window must not block the rest
                ok = False
            (closed if ok else failed).append(spawn["agent_name"])
            if not ok:
                logger.warning("shift: closing %s's window failed", spawn["agent_name"])
        # Close the books (design §8.1, D24): the sessions are gone, so every
        # unanswered in-flight message is undischargeable — release the lines, mark
        # the unfinished messages expired, keep everything in history.
        with self._storage.transaction() as uow:
            expired_lines, board_events = expire_open_work(uow)
        logger.info(
            "shift: ended (closed: %s; failed: %s; expired lines: %d)",
            closed or "-",
            failed or "-",
            len(expired_lines),
        )
        # keep what the ended shift did, for post-mortems (overwritten by the next one)
        self._doc = {
            "state": "off",
            "last": {
                **self._doc,
                "closed": closed,
                "failed": failed,
                "expired_lines": len(expired_lines),
            },
        }
        self._persist()
        return expired_lines, board_events

    def _publish_board(self, board_events: list, expired_lines: list) -> None:
        for message in board_events:
            self._events.publish("message", message)
        for line in expired_lines:
            self._events.publish("line", line)

    def tick(self) -> ShiftStatus | None:
        """Advance the machine; returns the new status when something changed."""
        with self._lock:
            state = self._doc.get("state")
            if state == "on":
                # Publish the transitions of the derived flags: D25's stale (the question
                # appears/vanishes) and D26's checking window ending (statuses verified).
                signature = (self._stale(), self._checking_until() is not None)
                if signature == self._last_on_signature:
                    return None
                self._last_on_signature = signature
                status = self._status()
            elif state == "starting":
                now = self._clock()
                if not self._doc.get("spawned"):
                    if now < datetime.fromisoformat(self._doc["grace_until"]):
                        return None
                    self._spawn_missing(now)
                    status = self._status()
                elif self._settled(now):
                    self._doc["state"] = "on"
                    self._persist()
                    logger.info("shift: on")
                    status = self._status()
                else:
                    return None
            else:
                return None
        self._publish(status)
        return status

    # -- internals (call with the lock held) -------------------------------------------

    def _judge_after(self) -> datetime:
        return self._hub_started_at + timedelta(seconds=self._heartbeat + GRACE_MARGIN_SECONDS)

    def _stale(self) -> bool:
        """D25: the shift reads on, the hub is old enough for liveness to be trusted
        (the D23 grace rule), not one launchable agent is connected, and none of the
        shift's windows are still open — the working period factually ended without the
        End gesture. Never true mid-restart (live agents re-attach within one heartbeat,
        inside the grace window) and never true while a spawned window merely waits on a
        first-run dialog (its tty is alive)."""
        if self._doc.get("state") != "on":
            return False
        if self._clock() < self._judge_after():
            return False
        targets, _ = self._targets()
        if not targets or any(agent.status == "connected" for agent in targets):
            return False
        if any(agent.status == "unknown" for agent in targets):
            return False  # D26: not yet judged — no claim, so no question yet either
        spawner = self._make_spawner(self._doc.get("terminal_app", "Terminal"))
        for spawn in self._doc.get("spawns", []):
            ref = spawn.get("window_ref")
            try:
                alive = bool(ref) and spawner.alive(ref)
            except Exception:  # noqa: BLE001 - an unverifiable window counts as dead
                alive = False
            if alive:
                return False  # a window is still open — not abandoned, just offline
        return True

    def _checking_until(self) -> datetime | None:
        """D26: the hub restarted into a running shift and liveness is not yet judged —
        the UI shows a "Checking the team" countdown instead of unverified statuses."""
        if self._doc.get("state") != "on":
            return None
        judge_after = self._judge_after()
        return judge_after if self._clock() < judge_after else None

    def _status(self) -> ShiftStatus:
        doc = self._doc
        return ShiftStatus(
            mode=self._settings.team_mode,
            state=doc.get("state", "off"),
            started_at=doc.get("started_at"),
            grace_until=doc.get("grace_until") if not doc.get("spawned") else None,
            spawns=doc.get("spawns", []),
            skipped=doc.get("skipped", []),
            stale=self._stale(),
            checking_until=self._checking_until(),
        )

    def _persist(self) -> None:
        with self._storage.transaction() as uow:
            uow.settings.set(SHIFT_KEY, self._doc)

    def _publish(self, status: ShiftStatus) -> None:
        self._events.publish("shift", status)

    def _targets(self) -> tuple[list[Agent], list[str]]:
        """(launchable agents, skipped names). claude-code and pi have launch profiles
        (D32); a dummy is a test twin, started by whoever is testing."""
        launchable: list[Agent] = []
        skipped: list[str] = []
        with self._storage.transaction() as uow:
            for agent in uow.agents.list():
                if agent.removed_at is not None or agent.type == "human":
                    continue
                if agent.type not in ("claude-code", "pi"):
                    skipped.append(agent.name)
                elif not agent.workdir:
                    skipped.append(agent.name)
                    logger.warning("shift: %s has no workdir — cannot launch", agent.name)
                else:
                    launchable.append(agent)
        return launchable, skipped

    def _spawn_missing(self, now: datetime) -> None:
        """Launch every target that is not connected and was not already spawned by this
        shift (a hub restart mid-start must never double-launch)."""
        targets, skipped = self._targets()
        already = {s["agent_name"] for s in self._doc.get("spawns", [])}
        spawner = self._make_spawner(self._doc.get("terminal_app", "Terminal"))
        for agent in targets:
            if agent.status == "connected" or agent.name in already:
                continue
            try:
                ref = spawner.spawn(agent.workdir, launch_command(agent))
            except Exception as exc:  # noqa: BLE001 - one failure must not stop the team
                logger.warning("shift: launching %s failed: %s", agent.name, exc)
                skipped.append(agent.name)
                continue
            self._doc["spawns"].append(
                {
                    "agent_id": str(agent.id),
                    "agent_name": agent.name,
                    "window_ref": ref,
                    "spawned_at": now.isoformat(),
                }
            )
            logger.info("shift: launched %s in %s", agent.name, agent.workdir)
        self._doc["spawned"] = True
        self._doc["skipped"] = skipped
        self._doc["settle_until"] = (now + timedelta(seconds=SETTLE_SECONDS)).isoformat()
        self._persist()

    def _settled(self, now: datetime) -> bool:
        if now >= datetime.fromisoformat(self._doc["settle_until"]):
            return True  # stragglers stay visible on their cards; the operator takes over
        targets, _ = self._targets()
        return all(agent.status == "connected" for agent in targets)

    def _busy_lines(self) -> int:
        with self._storage.transaction() as uow:
            return sum(1 for line in uow.lines.list() if line.state != "idle")
