"""Step 6b/6c — the Claude Code adapter.

The integration test speaks real JSON-RPC over pipes to the real `courtyard-claude-mcp`
process, against a real hub, exactly as Claude Code would: initialize, tools/call,
and — the part that matters — a hub delivery arriving as a `notifications/claude/channel`
event. No Claude Code and no model tokens are needed to prove the whole surface.

The envelope itself is the hub's (D14) and is tested in `test_envelope.py`; here it only
has to arrive intact.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time

import pytest

from courtyard.adapters.claude_code.mcp_server import (
    CHANNEL_NOTIFICATION,
    AdapterConfig,
    ConfigError,
    load_config,
)
from courtyard.common.client import HubClient
from courtyard.hub.core.peers import PEER_LIMIT


def test_config_requires_identity_and_token():
    with pytest.raises(ConfigError) as exc:
        load_config({"COURTYARD_HUB_URL": "http://127.0.0.1:2626"})
    assert "COURTYARD_TOKEN" in str(exc.value)

    config = load_config({"COURTYARD_AGENT_NAME": "coding", "COURTYARD_TOKEN": "t"})
    assert config == AdapterConfig("http://127.0.0.1:2626", "coding", "t", 5.0)


# -- the adapter process ----------------------------------------------------------------


class AdapterProcess:
    """Drives `courtyard-claude-mcp` over pipes, the way Claude Code drives it."""

    def __init__(self, hub_url: str, name: str, token: str):
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "courtyard.adapters.claude_code.mcp_server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env={
                **os.environ,
                "COURTYARD_HUB_URL": hub_url,
                "COURTYARD_AGENT_NAME": name,
                "COURTYARD_TOKEN": token,
                "COURTYARD_HEARTBEAT_SECONDS": "1",
            },
        )
        self._received: list[dict] = []
        self._lock = threading.Lock()
        self._stderr: queue.Queue[str] = queue.Queue()
        threading.Thread(target=self._pump_stdout, daemon=True).start()
        threading.Thread(target=self._pump_stderr, daemon=True).start()
        self._next_id = 0

    def _pump_stdout(self) -> None:
        for line in self.proc.stdout:
            line = line.strip()
            if line:
                with self._lock:
                    self._received.append(json.loads(line))

    def _pump_stderr(self) -> None:
        for line in self.proc.stderr:
            self._stderr.put(line.rstrip())

    def stderr_lines(self) -> list[str]:
        lines = []
        while not self._stderr.empty():
            lines.append(self._stderr.get_nowait())
        return lines

    def send(self, payload: dict) -> None:
        self.proc.stdin.write(json.dumps(payload) + "\n")
        self.proc.stdin.flush()

    def notify(self, method: str, params: dict | None = None) -> None:
        self.send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def request(self, method: str, params: dict | None = None, timeout: float = 10.0) -> dict:
        self._next_id += 1
        request_id = self._next_id
        self.send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})
        reply = self.wait_for(lambda m: m.get("id") == request_id, timeout)
        assert "error" not in reply, reply["error"]
        return reply["result"]

    def call_tool(self, name: str, arguments: dict | None = None) -> dict:
        return self.request("tools/call", {"name": name, "arguments": arguments or {}})

    def wait_for(self, match, timeout: float = 10.0) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                for item in self._received:
                    if match(item):
                        return item
            time.sleep(0.02)
        raise AssertionError(f"no matching message; got {self._received}\n{self.stderr_lines()}")

    def close(self) -> None:
        self.proc.stdin.close()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def tool_text(result: dict) -> str:
    return "\n".join(part["text"] for part in result["content"])


def wait_status(admin: HubClient, name: str, status: str, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        agent = next(a for a in admin.agents() if a.name == name)
        if agent.status == status:
            return
        time.sleep(0.05)
    raise AssertionError(f"{name} never became {status} (is {agent.status})")


@pytest.fixture()
def session(live_hub):
    """A hub with `coding` (the adapter) and `infra` (a peer) registered."""
    hub = live_hub()
    admin = HubClient(hub)
    _, coding_token = admin.register_agent(
        "coding", "claude-code", "writes the payments service", "the payments service"
    )
    _, infra_token = admin.register_agent(
        "infra", "puppet", "the infrastructure agent", "the staging and prod clusters"
    )
    adapter = AdapterProcess(hub, "coding", coding_token)
    yield adapter, admin, HubClient(hub, "infra", infra_token)
    adapter.close()
    admin.close()


def test_adapter_end_to_end(session):
    adapter, admin, infra = session

    # --- handshake: the channel capability is what makes deliveries become turns -----
    result = adapter.request(
        "initialize",
        {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "claude-code", "version": "2.1.237"},
        },
    )
    assert result["protocolVersion"] == "2025-06-18"  # echoes the client
    assert result["capabilities"]["experimental"] == {"claude/channel": {}}
    assert result["capabilities"]["tools"] == {}
    assert result["serverInfo"]["name"] == "courtyard"
    assert "at most one unanswered message" in result["instructions"]

    adapter.notify("notifications/initialized")
    wait_status(admin, "coding", "connected")  # attach happens after the handshake

    # --- tools ------------------------------------------------------------------------
    tools = {t["name"] for t in adapter.request("tools/list")["tools"]}
    assert tools == {"courtyard_send", "courtyard_inbox", "courtyard_peers", "courtyard_ack"}

    peers = tool_text(adapter.call_tool("courtyard_peers"))
    assert "infra — puppet, invited — owns: the staging and prod clusters" in peers
    assert "operator" in peers
    assert "coding" not in peers  # never lists itself

    assert "No unread" in tool_text(adapter.call_tool("courtyard_inbox"))

    # --- sending: the gate holds it, and the turn rule is legible --------------------
    held = adapter.call_tool("courtyard_send", {"to": "infra", "message": "can you deploy?"})
    assert held["isError"] is False
    assert "Held at the gate" in tool_text(held)

    again = adapter.call_tool("courtyard_send", {"to": "infra", "message": "hello?"})
    assert again["isError"] is True
    assert "gate_pending" in tool_text(again)

    (pending,) = admin.pending()
    assert pending.sender_name == "coding" and pending.body == "can you deploy?"
    admin.decide(pending.id, "approve")

    # --- delivery: infra's reply arrives as a channel notification -------------------
    reply = infra.send("coding", "cluster has capacity — go ahead")
    admin.decide(reply.id, "approve", "keep me posted")

    event = adapter.wait_for(
        lambda m: (
            m.get("method") == CHANNEL_NOTIFICATION
            and "cluster has capacity" in m["params"]["content"]
        )
    )
    assert event["params"]["meta"] == {"from": "infra", "kind": "message", "seq": str(reply.seq)}
    content = event["params"]["content"]
    assert content.startswith('<courtyard-message from="infra" authority="domain-owner"')
    assert "infra owns: the staging and prod clusters" in content
    assert "You own: the payments service" in content

    # the approve-note rides along as a separate operator note, framed as the operator
    note = adapter.wait_for(
        lambda m: (
            m.get("method") == CHANNEL_NOTIFICATION
            and m["params"]["meta"]["kind"] == "operator_note"
        )
    )
    assert "keep me posted" in note["params"]["content"]
    assert 'authority="operator"' in note["params"]["content"]

    # --- the reply closed the turn, so coding may send again -------------------------
    ok = adapter.call_tool("courtyard_send", {"to": "infra", "message": "merging now"})
    assert ok["isError"] is False

    # --- session end: closing stdin detaches -----------------------------------------
    adapter.close()
    wait_status(admin, "coding", "gone")
    assert not [line for line in adapter.stderr_lines() if "Traceback" in line]


def test_backlog_is_delivered_on_attach(session):
    """A message that arrived while the agent was down is handed over at attach time."""
    adapter, admin, infra = session
    queued = infra.send("coding", "I finished the migration while you were away")
    admin.decide(queued.id, "approve")

    adapter.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})
    adapter.notify("notifications/initialized")

    event = adapter.wait_for(lambda m: m.get("method") == CHANNEL_NOTIFICATION)
    assert "finished the migration" in event["params"]["content"]


def test_missing_environment_exits_with_a_clear_message():
    env = {k: v for k, v in os.environ.items() if not k.startswith("COURTYARD_")}
    proc = subprocess.run(
        [sys.executable, "-m", "courtyard.adapters.claude_code.mcp_server"],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
        check=False,  # a non-zero exit is exactly what this asserts
    )
    assert proc.returncode == 1
    assert "COURTYARD_TOKEN" in proc.stderr and "courtyard-invite" in proc.stderr
    assert proc.stdout == ""  # stdout is the protocol channel: never diagnostics


def test_peers_puts_reachable_agents_first_and_trims_dev_clutter(live_hub):
    """`courtyard_peers` is read by a model deciding whom to ask: a long tail of dead
    registrations is noise it pays context for. The ranking and the trim are the hub's
    (D14); this proves the adapter forwards what it gets."""
    hub = live_hub()
    admin = HubClient(hub)
    _, token = admin.register_agent("coding", "claude-code")
    for i in range(30):
        admin.register_agent(f"old-{i:02d}", "puppet", "a retired demo puppet")
    _, live_token = admin.register_agent("infra", "puppet", "owns the clusters")

    live = AdapterProcess(hub, "infra", live_token)
    live.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})
    live.notify("notifications/initialized")
    wait_status(admin, "infra", "connected")

    adapter = AdapterProcess(hub, "coding", token)
    adapter.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})
    try:
        listing = tool_text(adapter.call_tool("courtyard_peers")).splitlines()
        assert listing[1].startswith("infra — puppet, connected")  # reachable first
        assert len(listing) <= PEER_LIMIT + 2  # header + the limit + the elision line
        assert "more registrations that have not been active" in listing[-1]
    finally:
        adapter.close()
        live.close()
        admin.close()


def test_adapter_attaches_when_the_hub_arrives_late(live_hub, config):
    """Agents-first, hub-second must work (feedback item 12): the adapter keeps retrying
    attach instead of giving up after ~10s and leaving the agent permanently offline."""
    from dataclasses import replace as dc_replace

    import uvicorn

    from conftest import _free_port
    from courtyard.hub.main import create_app

    hub_a = live_hub()  # only to register the agent; state lives in the shared DB
    admin = HubClient(hub_a)
    _, token = admin.register_agent("coding", "claude-code", "late-hub twin")

    port = _free_port()  # nothing listens here yet — the adapter retries against it
    adapter = AdapterProcess(f"http://127.0.0.1:{port}", "coding", token)
    server = None
    try:
        adapter.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})
        adapter.notify("notifications/initialized")
        time.sleep(11.0)  # well past the original five-attempts-then-give-up horizon

        cfg = dc_replace(config, port=port)  # the hub finally appears where it was expected
        server = uvicorn.Server(
            uvicorn.Config(create_app(cfg), host=cfg.host, port=cfg.port, log_level="warning")
        )
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        deadline = time.monotonic() + 15
        while not server.started:
            assert time.monotonic() < deadline, "late test hub failed to start"
            time.sleep(0.02)

        wait_status(admin, "coding", "connected")  # via hub A — same database
    finally:
        adapter.close()
        if server is not None:
            server.should_exit = True
        admin.close()


def test_judge_channel_flag_from_process_ancestry():
    """Item 33 (D29): the launch flag is the deterministic tell for channel-less
    sessions; wrappers around the adapter itself must not be mistaken for claude."""
    from courtyard.adapters.claude_code.mcp_server import judge_channel_flag

    flagged = "claude --dangerously-load-development-channels server:courtyard --model haiku"
    assert judge_channel_flag([flagged]) == "present"
    assert judge_channel_flag(["claude"]) == "absent"
    assert judge_channel_flag(["/bin/zsh -c courtyard-claude-mcp", flagged]) == "present"
    assert judge_channel_flag(["sh -c courtyard-claude-mcp", "claude --model haiku"]) == "absent"
    assert judge_channel_flag(["/usr/bin/login", "-zsh"]) == "unknown"
    assert judge_channel_flag([]) == "unknown"
