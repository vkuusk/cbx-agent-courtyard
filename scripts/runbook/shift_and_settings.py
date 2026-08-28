"""Runbook check: the shift state machine and the Team settings (design §8.1, D23).

  1. settings: defaults, terminal app round trip, `always_on` and junk values refused
  2. shift: off -> starting (grace countdown after a fresh hub start; instant later)
     -> on -> off, watched over GET /api/shift
  3. the throwaway agent is a puppet, so the shift SKIPS it — this script never opens a
     real terminal window. The real-spawn check is the manual procedure in
     docs/testing-runbook.md (press the pill with a claude-code agent down).

Run against a hub started with `make run`:
    uv run python scripts/runbook/shift_and_settings.py
"""

import time

from courtyard.common.client import HubClient, HubError

HUB = "http://127.0.0.1:2626"


def hr(title):
    print("\n" + "=" * 78 + f"\n{title}\n" + "=" * 78)


admin = HubClient(HUB)
name = f"shift-rb-{str(time.time_ns())[-7:]}"
admin.register_agent(name, "puppet", "runbook twin", None, None)
print(f"registered throwaway puppet {name} (the shift skips puppets — nothing will spawn)")

hr("1. SETTINGS  (GET/PATCH /api/settings)")
settings = admin._call("GET", "/api/settings")
print(f"defaults      : {settings}")
saved = admin._call("PATCH", "/api/settings", {"terminal_app": "iTerm2"})
print(f"iTerm2 saved  : {saved['terminal_app'] == 'iTerm2'}")
admin._call("PATCH", "/api/settings", {"terminal_app": settings["terminal_app"]})
print(f"restored      : {admin._call('GET', '/api/settings')['terminal_app']}")
try:
    admin._call("PATCH", "/api/settings", {"team_mode": "always_on"})
    print("always_on     : ACCEPTED — that is a bug (v1 implements on_shift only)")
except HubError as exc:
    print(f"always_on     : refused ({exc})")
# custom terminal apps (item 20): add, select, and the refusals; restored afterwards
saved = admin._call(
    "PATCH",
    "/api/settings",
    {"custom_terminals": [{"name": "rb-term", "command": "true {command}"}]},
)
admin._call("PATCH", "/api/settings", {"terminal_app": "rb-term"})
print("custom app    : added and selected (rb-term)")
try:
    admin._call(
        "PATCH", "/api/settings", {"custom_terminals": [{"name": "rb-term", "command": "true"}]}
    )
    print("no {command}  : ACCEPTED — that is a bug")
except HubError as exc:
    print(f"no {{command}}  : refused ({exc.code})")
admin._call(
    "PATCH", "/api/settings", {"terminal_app": settings["terminal_app"], "custom_terminals": []}
)
print(f"restored      : {admin._call('GET', '/api/settings')['terminal_app']}, no custom apps")

hr("2. SHIFT  (POST /api/shift/start -> GET /api/shift -> POST /api/shift/end)")
# Guards: on a dev hub with REAL claude-code agents currently down, Start shift would
# open real terminal windows for them; and since D24, a forced End shift closes the
# books — every non-idle line is released and its unanswered message expires. Neither
# may touch real work, so both conditions skip this section.
down = [
    a["name"]
    for a in admin._call("GET", "/api/agents")
    if a["type"] == "claude-code"
    and not a["removed_at"]
    and a["workdir"]
    and a["status"] != "connected"
]
busy = [ln for ln in admin._call("GET", "/api/lines") if ln["state"] != "idle"]
if down or busy:
    if down:
        print(f"SKIPPED: claude-code agent(s) down ({', '.join(down)}) — starting the shift")
        print("would open real terminals for them. Start their sessions (or remove them),")
        print("or do the manual pill check in docs/testing-runbook.md instead.")
    if busy:
        print(f"SKIPPED: {len(busy)} line(s) are mid-conversation — ending the shift with")
        print("force would expire their unanswered messages (D24). Finish or release them.")
    admin._call("DELETE", f"/api/agents/{name}")
    admin.close()
    raise SystemExit(0)
print(f"before        : {admin._call('GET', '/api/shift')['state']}")
status = admin._call("POST", "/api/shift/start")
print(
    f"after start   : {status['state']}"
    + (
        f"   (grace countdown until {status['grace_until']} — the hub is young)"
        if status.get("grace_until")
        else "   (no countdown — the hub has been up a while)"
    )
)
deadline = time.time() + 90
while status["state"] != "on" and time.time() < deadline:
    time.sleep(1)
    status = admin._call("GET", "/api/shift")
print(
    f"settled       : {status['state']}   spawned: {len(status['spawns'])}"
    f"   skipped: {status['skipped']}   <- the puppet is skipped, nothing spawned"
)
try:
    status = admin._call("POST", "/api/shift/end", {"force": False})
except HubError as exc:  # lines mid-conversation on this dev hub; nothing was spawned
    print(f"end refused   : {exc} -> forcing (this shift opened no windows)")
    status = admin._call("POST", "/api/shift/end", {"force": True})
print(f"after end     : {status['state']}")

admin._call("DELETE", f"/api/agents/{name}")
admin.close()
print("\n(cleaned up the throwaway puppet.)")
