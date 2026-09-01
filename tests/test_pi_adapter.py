"""The pi adapter (item 36, D32): the rendered extension, driven under Node with a
stub `pi` object against a real hub — the wire-level e2e a real pi session performs.
Skipped when Node is not on PATH (Claude Code environments always have it).
"""

from __future__ import annotations

import json
import queue
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest

from courtyard.common.client import HubClient
from courtyard.hub.core import install as install_core

HARNESS = Path(__file__).parent / "pi_harness.mjs"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not on PATH")


class Harness:
    def __init__(self, ext_path: Path):
        self.proc = subprocess.Popen(
            [shutil.which("node"), str(HARNESS)],
            env={"COURTYARD_EXT": str(ext_path)},
            cwd=ext_path.parent,  # `.courtyard/adapter.log` lands beside the extension
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        self.events: queue.Queue = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        for line in self.proc.stdout:
            self.events.put(json.loads(line))

    def wait_for(self, predicate, timeout=10.0, what="event"):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                event = self.events.get(timeout=0.2)
            except queue.Empty:
                continue
            if predicate(event):
                return event
        raise AssertionError(f"{what} never arrived")

    def send(self, command: dict) -> None:
        self.proc.stdin.write(json.dumps(command) + "\n")
        self.proc.stdin.flush()

    def call(self, tool: str, **params):
        self.send({"call": tool, "params": params})
        return self.wait_for(
            lambda e: e["event"] in ("tool_result", "tool_error") and e["name"] == tool,
            what=f"result of {tool}",
        )

    def stop(self) -> None:
        if self.proc.poll() is None:
            self.proc.kill()


def wait_agent(admin, name, predicate, timeout=8.0, what="agent state"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        agent = next(a for a in admin.agents() if a.name == name)
        if predicate(agent):
            return agent
        time.sleep(0.05)
    raise AssertionError(f"{what} never happened (agent is {agent})")


def test_pi_extension_end_to_end(live_hub, tmp_path):
    hub = live_hub()
    admin = HubClient(hub)
    _, token = admin.register_agent("pibot", "pi", "the pi twin", None, str(tmp_path))

    # The exact file install writes, rendered with this agent's connection. Node
    # needs an .mjs suffix; pi itself loads the .ts via jiti.
    ext = tmp_path / "courtyard.mjs"
    ext.write_text(install_core.pi_extension(hub, "pibot", token))
    harness = Harness(ext)
    try:
        harness.wait_for(
            lambda e: e["event"] == "command_registered" and e["name"] == "courtyard",
            what="/courtyard command",
        )
        for tool in ("courtyard_send", "courtyard_inbox", "courtyard_peers", "courtyard_ack"):
            harness.wait_for(
                lambda e, t=tool: e["event"] == "tool_registered" and e["name"] == t,
                what=f"{tool} registration",
            )
        harness.wait_for(lambda e: e["event"] == "started", what="session_start")
        agent = wait_agent(admin, "pibot", lambda a: a.status == "connected", what="attach")
        assert agent.channel_flag == "present"  # the extension IS the channel
        # The footer status is the live pi analog of the claude status line (item 2).
        harness.wait_for(
            lambda e: e["event"] == "setStatus" and "connected" in e["text"] and "pibot" in e["text"],
            what="footer status",
        )
        # /courtyard answers in the TUI without involving the LLM.
        harness.send({"command": "courtyard"})
        harness.wait_for(
            lambda e: e["event"] == "notify" and "connected as pibot" in e["text"],
            what="/courtyard notify",
        )

        # Hub -> session: a push arrives as a courtyard custom message that wakes
        # an idle session and queues politely on a busy one.
        admin._call("POST", "/api/operator/send", {"to": "pibot", "body": "hello pibot"})
        push = harness.wait_for(lambda e: e["event"] == "sendMessage", what="channel push")
        assert push["message"]["customType"] == "courtyard"
        assert "<courtyard-message" in push["message"]["content"]
        assert "hello pibot" in push["message"]["content"]
        assert push["options"] == {"triggerTurn": True, "deliverAs": "followUp"}

        # Session -> hub: the reply travels the same turn machine as every agent's.
        result = harness.call("courtyard_send", to="operator", message="hi back")
        assert result["event"] == "tool_result" and "Delivered to operator" in result["text"]

        # A turn violation is surfaced verbatim, as a tool error the model reads:
        # the reply above closed the exchange, this opens a new one (allowed), and
        # a further send while the operator owes the answer is refused.
        opened = harness.call("courtyard_send", to="operator", message="a new question")
        assert opened["event"] == "tool_result"
        violation = harness.call("courtyard_send", to="operator", message="impatience")
        assert violation["event"] == "tool_error"
        assert "courtyard hub refused" in violation["text"]

        # The delivery check (item 34) works unchanged on pi.
        admin.verify_delivery("pibot")
        check = harness.wait_for(
            lambda e: e["event"] == "sendMessage" and "courtyard_ack" in e["message"]["content"],
            what="delivery check push",
        )
        check_token = re.search(r'token "([^"]+)"', check["message"]["content"]).group(1)
        ack = harness.call("courtyard_ack", token=check_token)
        assert "Delivery confirmed" in ack["text"]
        wait_agent(admin, "pibot", lambda a: a.delivery_check == "verified", what="verified")

        peers = harness.call("courtyard_peers")
        assert peers["event"] == "tool_result" and peers["text"].strip()

        # Clean shutdown detaches; liveness goes gone immediately.
        harness.send({"cmd": "shutdown"})
        harness.wait_for(lambda e: e["event"] == "shutdown", what="shutdown")
        wait_agent(admin, "pibot", lambda a: a.status == "gone", what="detach")

        # The delivery trail: `.courtyard/adapter.log` in the workdir.
        log = (tmp_path / ".courtyard/adapter.log").read_text()
        assert "attached as pibot" in log and "delivered kind=" in log and "detached" in log
    finally:
        harness.stop()
        admin.close()
