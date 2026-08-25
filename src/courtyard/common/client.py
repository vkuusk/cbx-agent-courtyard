"""Hub client library — the adapter contract (design §7.1), implemented once.

`HubClient` covers the adapter-to-hub half (attach, send, pull, heartbeat, detach) plus
the operator/admin calls scripts and tests need. `ChannelReceiver` covers the
hub-to-adapter half: a tiny local HTTP listener that authenticates the hub's pushes with
the channel token and hands each message to a callback.

The callback must return quickly (enqueue, don't process): the hub's push waits on it,
and an exception or timeout counts as a failed delivery (the message stays queued).
"""

from __future__ import annotations

import json
import secrets
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from uuid import UUID

import httpx

from courtyard.common.models import Agent, Archive, AttachSummary, Line, Message, PeersView

CHANNEL_TOKEN_HEADER = "X-Courtyard-Channel-Token"
DEFAULT_HUB_URL = "http://127.0.0.1:2626"


class HubError(Exception):
    """A machine-readable hub error, surfaced verbatim (turn violations are meant to be
    read by LLMs — don't wrap or soften them)."""

    def __init__(self, http_status: int, code: str, message: str, extra: dict | None = None):
        super().__init__(message)
        self.http_status = http_status
        self.code = code
        self.extra = extra or {}

    def __str__(self) -> str:
        return f"[{self.code}] {super().__str__()}"


class HubClient:
    def __init__(
        self,
        hub_url: str = DEFAULT_HUB_URL,
        name: str | None = None,
        token: str | None = None,
        timeout: float = 10.0,
    ):
        self.hub_url = hub_url.rstrip("/")
        self.name = name
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._http = httpx.Client(base_url=self.hub_url, headers=headers, timeout=timeout)

    def close(self) -> None:
        self._http.close()

    def _call(self, method: str, path: str, json_body: dict | None = None) -> Any:
        resp = self._http.request(method, path, json=json_body)
        if resp.is_success:
            return resp.json() if resp.content else None  # 204: no body
        try:
            error = resp.json()["error"]
        except (json.JSONDecodeError, KeyError):
            raise HubError(resp.status_code, "http_error", resp.text) from None
        known = {"code", "message"}
        extra = {k: v for k, v in error.items() if k not in known}
        raise HubError(resp.status_code, error["code"], error["message"], extra)

    # -- the adapter contract --------------------------------------------------------

    def attach(self, endpoint: str, channel_token: str) -> AttachSummary:
        data = self._call(
            "POST",
            f"/api/agents/{self.name}/attach",
            {"endpoint": endpoint, "channel_token": channel_token},
        )
        return AttachSummary.model_validate(data)

    def send(self, to: str, body: str) -> Message:
        return Message.model_validate(
            self._call("POST", "/api/lines/send", {"to": to, "body": body})
        )

    def inbox(self) -> list[Message]:
        data = self._call("GET", f"/api/agents/{self.name}/inbox")
        return [Message.model_validate(m) for m in data]

    def peers(self) -> PeersView:
        return PeersView.model_validate(self._call("GET", f"/api/agents/{self.name}/peers"))

    def heartbeat(self) -> dict:
        return self._call("POST", f"/api/agents/{self.name}/heartbeat")

    def detach(self) -> None:
        self._call("POST", f"/api/agents/{self.name}/detach")

    # -- registry / board reads ------------------------------------------------------

    def register_agent(
        self,
        name: str,
        type: str,
        description: str | None = None,
        sme_domain: str | None = None,
        workdir: str | None = None,
        color: str | None = None,
        model: str | None = None,
    ) -> tuple[Agent, str]:
        data = self._call(
            "POST",
            "/api/agents",
            {
                "name": name,
                "type": type,
                "description": description,
                "sme_domain": sme_domain,
                "workdir": workdir,
                "color": color,
                "model": model,
            },
        )
        return Agent.model_validate(data["agent"]), data["token"]

    def agents(self) -> list[Agent]:
        return [Agent.model_validate(a) for a in self._call("GET", "/api/agents")]

    def install(self, name: str, token: str | None = None, workdir: str | None = None) -> dict:
        """Write the agent's `.mcp.json` into its workdir (dev mode). Returns {path, ...}.
        The hub keeps the token (D19); pass one only to insist on a specific value."""
        return self._call(
            "POST", f"/api/agents/{name}/install", {"token": token, "workdir": workdir}
        )

    def token_of(self, name: str) -> str:
        """The agent's stored token (D19)."""
        return self._call("GET", f"/api/agents/{name}/token")["token"]

    def rotate_token(self, name: str) -> tuple[Agent, str]:
        """Replace the agent's token; the old one stops working at once."""
        data = self._call("POST", f"/api/agents/{name}/token")
        return Agent.model_validate(data["agent"]), data["token"]

    def uninstall(self, name: str, workdir: str | None = None) -> dict:
        return self._call("POST", f"/api/agents/{name}/uninstall", {"workdir": workdir})

    def lines(self) -> list[Line]:
        return [Line.model_validate(li) for li in self._call("GET", "/api/lines")]

    def line_messages(self, line_id: UUID | str, after: int | None = None) -> list[Message]:
        path = f"/api/lines/{line_id}/messages"
        if after is not None:
            path += f"?after={after}"
        return [Message.model_validate(m) for m in self._call("GET", path)]

    # -- operator actions (admin surface, unauthenticated in v1) ----------------------

    def pending(self) -> list[Message]:
        return [Message.model_validate(m) for m in self._call("GET", "/api/gate/pending")]

    def decide(self, message_id: UUID | str, verdict: str, note: str | None = None) -> Message:
        return Message.model_validate(
            self._call("POST", f"/api/gate/{message_id}", {"verdict": verdict, "note": note})
        )

    def set_mode(self, line_id: UUID | str, mode: str) -> Line:
        return Line.model_validate(self._call("POST", f"/api/lines/{line_id}/mode", {"mode": mode}))

    def archive_line(self, line_id: UUID | str) -> Archive:
        """Archive the line's history so far; the line continues empty (design §5.7)."""
        return Archive.model_validate(self._call("POST", f"/api/lines/{line_id}/archive"))

    def archives(self) -> list[Archive]:
        return [Archive.model_validate(a) for a in self._call("GET", "/api/archive")]

    def archive(self, archive_id: UUID | str) -> Archive:
        return Archive.model_validate(self._call("GET", f"/api/archive/{archive_id}"))

    def delete_archive(self, archive_id: UUID | str) -> None:
        self._call("DELETE", f"/api/archive/{archive_id}")

    def release(self, line_id: UUID | str) -> Line:
        return Line.model_validate(self._call("POST", f"/api/lines/{line_id}/release"))


class ChannelReceiver:
    """The adapter's receive endpoint: bind an ephemeral localhost port, verify the
    channel token on every push, hand the message to the callback."""

    def __init__(self, on_message: Callable[[Message], None], host: str = "127.0.0.1"):
        self.channel_token = secrets.token_urlsafe(24)
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                if self.headers.get(CHANNEL_TOKEN_HEADER) != receiver.channel_token:
                    self._respond(401, {"error": "bad channel token"})
                    return
                length = int(self.headers.get("Content-Length", 0))
                try:
                    payload = json.loads(self.rfile.read(length))
                    message = Message.model_validate(payload["message"])
                    on_message(message)
                except Exception as exc:  # noqa: BLE001 - a 500 = failed delivery, stays queued
                    self._respond(500, {"error": str(exc)})
                    return
                self._respond(200, {"ok": True})

            def _respond(self, status: int, body: dict) -> None:
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args: Any) -> None:  # silence stdlib request logging
                return

        self._server = ThreadingHTTPServer((host, 0), Handler)
        self.endpoint = f"http://{host}:{self._server.server_address[1]}/"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
