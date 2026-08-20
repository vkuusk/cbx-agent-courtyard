"""The puppet runtime: channel receiver + worker + heartbeat around a behavior."""

from __future__ import annotations

import queue
import threading
import time
from datetime import datetime
from typing import Protocol

import httpx

from courtyard.common.client import ChannelReceiver, HubClient, HubError
from courtyard.common.models import AttachSummary, Message


class Behavior(Protocol):
    def on_message(self, message: Message, puppet: Puppet) -> None: ...


class Puppet:
    """Attaches to the hub, receives pushes, and lets a behavior react.

    The channel handler only enqueues (the hub's push must return fast); a single worker
    thread processes messages in order. Message ids are deduplicated so a push/pull race
    or a re-delivered backlog is never double-processed.
    """

    def __init__(
        self,
        hub_url: str,
        name: str,
        token: str,
        behavior: Behavior,
        heartbeat_seconds: float = 30.0,
    ):
        self.name = name
        self.client = HubClient(hub_url, name, token)
        self.behavior = behavior
        self.heartbeat_seconds = heartbeat_seconds
        self.summary: AttachSummary | None = None
        self.last_peer: str | None = None  # whom I last sent to (reply target for notices)
        self._queue: queue.Queue[Message] = queue.Queue()
        self._seen: set = set()
        self._stop = threading.Event()
        self._print_lock = threading.Lock()
        self.receiver: ChannelReceiver | None = None

    # -- lifecycle -------------------------------------------------------------------

    def start(self) -> AttachSummary:
        self.receiver = ChannelReceiver(self._queue.put)
        self.summary = self.client.attach(self.receiver.endpoint, self.receiver.channel_token)
        threading.Thread(target=self._work, daemon=True).start()
        threading.Thread(target=self._beat, daemon=True).start()
        return self.summary

    def stop(self) -> None:
        self._stop.set()
        try:
            self.client.detach()
        except (HubError, httpx.HTTPError):
            pass
        if self.receiver is not None:
            self.receiver.stop()
        self.client.close()

    def wait(self) -> None:
        """Block until stop() (for non-interactive behaviors)."""
        while not self._stop.wait(0.5):
            pass

    # -- actions ---------------------------------------------------------------------

    def say(self, to: str, body: str) -> Message | None:
        """Send; hub verdicts and violations are printed verbatim, never raised away."""
        self.last_peer = to
        try:
            message = self.client.send(to, body)
        except HubError as exc:
            self.log(f"hub refused send to {to}: {exc}")
            return None
        if message.status == "pending_gate":
            self.log(f"→ {to} (seq {message.seq}) — held at the gate, awaiting the operator")
        else:
            self.log(f"→ {to} (seq {message.seq}, {message.status}): {body}")
        return message

    def log(self, text: str) -> None:
        with self._print_lock:
            now = datetime.now()  # noqa: DTZ005 - local wall clock is right for a terminal
            print(f"[{now:%H:%M:%S}] {text}", flush=True)

    def show(self, m: Message) -> None:
        sender = m.sender_name or "hub"
        kind = "" if m.kind == "message" else f" [{m.kind}]"
        self.log(f"{sender} → you (seq {m.seq}){kind}: {m.body}")

    # -- internals -------------------------------------------------------------------

    def _work(self) -> None:
        while not self._stop.is_set():
            try:
                message = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if message.id in self._seen:
                continue
            self._seen.add(message.id)
            try:
                self.behavior.on_message(message, self)
            except Exception as exc:  # noqa: BLE001 - a behavior bug must not kill the puppet
                self.log(f"behavior error on seq {message.seq}: {exc}")

    def _beat(self) -> None:
        while not self._stop.wait(self.heartbeat_seconds):
            try:
                if self.client.heartbeat().get("queued"):
                    # The pull path: pick up anything a failed push left behind (design §6.1).
                    for message in self.client.inbox():
                        self._queue.put(message)
            except (HubError, httpx.HTTPError) as exc:
                self.log(f"heartbeat failed: {exc}")


class EchoBehavior:
    """Acknowledge every message — the endless turn-machine exerciser."""

    def on_message(self, m: Message, puppet: Puppet) -> None:
        puppet.show(m)
        if m.kind != "message":  # never auto-reply to notes or system notices
            return
        time.sleep(0.3)
        puppet.say(m.sender_name, f"ack (echo): received your seq {m.seq}: {m.body[:120]}")


class ScriptStep:
    def __init__(
        self,
        reply: str,
        match: str | None = None,
        delay: float = 0.5,
        kind: str = "message",
        to: str | None = None,
    ):
        self.reply = reply
        self.match = match
        self.delay = delay
        self.kind = kind  # which incoming kind this step reacts to (message/system/operator_note)
        self.to = to  # explicit target; default: the sender, or last peer for hub notices
        self.used = False


class ScriptBehavior:
    """Deterministic conversation: on each incoming message, the first unused step of the
    matching kind whose `match` substring occurs in the body (case-insensitive; no match =
    always) fires once. Exhausted or unmatched -> stay silent.

    Steps with `kind: system` let a puppet react to gate outcomes — e.g. resend a revised
    message after a return-to-sender."""

    def __init__(self, steps: list[ScriptStep]):
        self._steps = steps

    @classmethod
    def from_yaml(cls, path: str) -> ScriptBehavior:
        import yaml

        with open(path) as f:
            spec = yaml.safe_load(f)
        steps = [
            ScriptStep(
                reply=s["reply"],
                match=s.get("match"),
                delay=float(s.get("delay", 0.5)),
                kind=s.get("kind", "message"),
                to=s.get("to"),
            )
            for s in spec["steps"]
        ]
        return cls(steps)

    def on_message(self, m: Message, puppet: Puppet) -> None:
        puppet.show(m)
        for step in self._steps:
            if step.used or step.kind != m.kind:
                continue
            if step.match and step.match.lower() not in m.body.lower():
                continue
            step.used = True
            time.sleep(step.delay)
            target = step.to or m.sender_name or puppet.last_peer
            if target is None:
                puppet.log("(script step fired but there is no target to send to)")
                return
            puppet.say(target, step.reply)
            return
        if m.kind == "message":
            puppet.log(f"(script has no reply for seq {m.seq}; staying silent)")


class ManualBehavior:
    """Print everything; the human replies from the terminal (the REPL lives in the CLI)."""

    def __init__(self) -> None:
        self.last_sender: str | None = None

    def on_message(self, m: Message, puppet: Puppet) -> None:
        puppet.show(m)
        if m.kind == "message" and m.sender_name:
            self.last_sender = m.sender_name
