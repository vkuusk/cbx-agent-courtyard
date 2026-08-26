"""The Shift (design §8.1, D23): one operator gesture that starts every registered agent
not already up, and ends by closing exactly what it started.

State machine: off -> starting (grace countdown, then spawn) -> on -> off. The grace
window exists for one reason: after a hub restart a healthy agent looks down until its
adapter's next heartbeat re-attaches, and spawning during that window would start a
second session on the same identity. So liveness is judged only once the hub has been up
for one heartbeat interval (+ margin); when the hub is older than that — the common case
— start is instant.

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

from courtyard.common.models import Agent, Settings, ShiftStatus
from courtyard.hub.core.errors import InvalidSetting, ShiftBusy
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


def launch_command(agent: Agent) -> str:
    return CLAUDE_LAUNCH + (f" --model {agent.model}" if agent.model else "")


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
        spawner_factory: Callable[[str], TerminalSpawner] = make_spawner,
        hub_started_at: datetime | None = None,
    ):
        self._storage = storage
        self._events = events
        self._heartbeat = heartbeat_seconds
        self._clock = clock
        self._make_spawner = spawner_factory
        self._hub_started_at = hub_started_at or clock()
        self._lock = threading.Lock()
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
            with self._storage.transaction() as uow:
                uow.settings.set(SETTINGS_KEY, merged.model_dump())
            self._settings = merged
            return merged

    # -- the shift --------------------------------------------------------------------

    def status(self) -> ShiftStatus:
        with self._lock:
            return self._status()

    def start(self) -> ShiftStatus:
        """Idempotent: pressing Start during a running shift changes nothing."""
        with self._lock:
            if self._doc.get("state") == "off":
                now = self._clock()
                self._doc = {
                    "state": "starting",
                    "started_at": now.isoformat(),
                    "grace_until": max(now, self._judge_after()).isoformat(),
                    "terminal_app": self._settings.terminal_app,
                    "spawned": False,
                    "spawns": [],
                    "skipped": [],
                }
                self._persist()
                logger.info("shift: starting (grace until %s)", self._doc["grace_until"])
            status = self._status()
        self._publish(status)
        return self.tick() or status

    def end(self, force: bool = False) -> ShiftStatus:
        """Close what the shift opened; refuse (without force) while lines are mid-work."""
        with self._lock:
            if self._doc.get("state") == "off":
                return self._status()
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
            logger.info("shift: ended (closed: %s; failed: %s)", closed or "-", failed or "-")
            # keep what the ended shift did, for post-mortems (overwritten by the next one)
            self._doc = {"state": "off", "last": {**self._doc, "closed": closed, "failed": failed}}
            self._persist()
            status = self._status()
        self._publish(status)
        return status

    def tick(self) -> ShiftStatus | None:
        """Advance the machine; returns the new status when something changed."""
        with self._lock:
            if self._doc.get("state") != "starting":
                return None
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
        self._publish(status)
        return status

    # -- internals (call with the lock held) -------------------------------------------

    def _judge_after(self) -> datetime:
        return self._hub_started_at + timedelta(seconds=self._heartbeat + GRACE_MARGIN_SECONDS)

    def _status(self) -> ShiftStatus:
        doc = self._doc
        return ShiftStatus(
            mode=self._settings.team_mode,
            state=doc.get("state", "off"),
            started_at=doc.get("started_at"),
            grace_until=doc.get("grace_until") if not doc.get("spawned") else None,
            spawns=doc.get("spawns", []),
            skipped=doc.get("skipped", []),
        )

    def _persist(self) -> None:
        with self._storage.transaction() as uow:
            uow.settings.set(SHIFT_KEY, self._doc)

    def _publish(self, status: ShiftStatus) -> None:
        self._events.publish("shift", status)

    def _targets(self) -> tuple[list[Agent], list[str]]:
        """(launchable agents, skipped names). v1 launches claude-code only — a puppet is
        a test twin, started by whoever is testing; other types have no launch profile."""
        launchable: list[Agent] = []
        skipped: list[str] = []
        with self._storage.transaction() as uow:
            for agent in uow.agents.list():
                if agent.removed_at is not None or agent.type == "human":
                    continue
                if agent.type != "claude-code":
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
