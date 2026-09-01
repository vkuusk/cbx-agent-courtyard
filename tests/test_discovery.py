"""Discovery auto|manual (design §5.8, D22): under manual, a link — a pre-created idle
line — is the permission for two agents to talk; the operator wires the team and is
himself exempt. Switching modes migrates nothing: existing lines ARE the links."""

from conftest import auth
from courtyard.common.models import Agent
from courtyard.hub.core.peers import peers_view, render, roster

DEAD_ENDPOINT = "http://127.0.0.1:1/"


def send(client, token, to, body="hello"):
    return client.post("/api/lines/send", json={"to": to, "body": body}, headers=auth(token))


def set_discovery(client, value):
    resp = client.patch("/api/settings", json={"discovery": value})
    assert resp.status_code == 200, resp.text


def link(client, a, b):
    return client.post("/api/lines", json={"a": a, "b": b})


def peers_of(client, name, token):
    return client.get(f"/api/agents/{name}/peers", headers=auth(token)).json()


def attach(client, name, token):
    return client.post(
        f"/api/agents/{name}/attach",
        json={"endpoint": DEAD_ENDPOINT, "channel_token": "ct"},
        headers=auth(token),
    )


# -- the pure filter -------------------------------------------------------------------


def _agent(name, type="dummy", status="connected"):
    return Agent.model_construct(
        id=name,
        name=name,
        type=type,
        status=status,
        removed_at=None,
        description=None,
        sme_domain=None,
    )


def test_roster_filters_to_linked_plus_operator():
    me = _agent("me")
    agents = [me, _agent("operator", type="human"), _agent("linked"), _agent("stranger")]
    assert [p.name for p in roster(agents, me)] == ["linked", "operator", "stranger"]
    filtered = roster(agents, me, linked={"linked"})
    assert [p.name for p in filtered] == ["linked", "operator"]


def test_rendered_text_names_the_regime():
    me = _agent("me")
    agents = [me, _agent("peer")]
    open_view = peers_view(agents, me)
    assert "operator manages the links" not in open_view.rendered
    managed = peers_view(agents, me, linked={"peer"})
    assert "the operator manages the links" in managed.rendered
    assert render([], 0, managed=True) == (
        "You have no lines yet — the operator links agents in this courtyard."
    )


# -- the send guard --------------------------------------------------------------------


def test_manual_send_refused_without_a_line(client, make_agent):
    _, alice = make_agent("alice")
    make_agent("bob")
    set_discovery(client, "manual")
    resp = send(client, alice, "bob")
    assert resp.status_code == 409
    error = resp.json()["error"]
    assert error["code"] == "not_linked"
    assert "the operator links agents" in error["message"]


def test_operator_needs_no_links_in_either_direction(client, make_agent):
    _, alice = make_agent("alice")
    set_discovery(client, "manual")
    resp = client.post("/api/operator/send", json={"to": "alice", "body": "hi"})
    assert resp.status_code == 201, resp.text
    # alice owes the operator a reply on that line; the reverse direction is the reply
    assert send(client, alice, "operator", "hello back").status_code == 201


def test_lines_formed_in_auto_keep_working_after_the_switch(client, make_agent):
    _, alice = make_agent("alice")
    make_agent("bob")
    make_agent("carol")
    first = send(client, alice, "bob", "before the switch")
    assert first.status_code == 201  # auto: the line forms on first message
    client.post(f"/api/gate/{first.json()['id']}", json={"verdict": "drop", "note": None})
    set_discovery(client, "manual")
    assert send(client, alice, "bob", "after the switch").status_code == 201
    assert send(client, alice, "carol").json()["error"]["code"] == "not_linked"


# -- link ------------------------------------------------------------------------------


def test_link_creates_an_idle_line_with_the_default_mode(client, make_agent):
    make_agent("alice")
    make_agent("bob")
    set_discovery(client, "manual")
    client.patch("/api/settings", json={"default_line_mode": "auto_pass"})
    resp = link(client, "alice", "bob")
    assert resp.status_code == 201, resp.text
    line = resp.json()
    assert line["state"] == "idle" and line["mode"] == "auto_pass"


def test_linked_pair_can_talk(client, make_agent):
    _, alice = make_agent("alice")
    make_agent("bob")
    set_discovery(client, "manual")
    assert link(client, "alice", "bob").status_code == 201
    assert send(client, alice, "bob").status_code == 201


def test_link_refusals(client, make_agent):
    make_agent("alice")
    make_agent("bob")
    resp = link(client, "alice", "bob")
    assert resp.status_code == 201
    assert link(client, "alice", "bob").json()["error"]["code"] == "already_linked"
    assert link(client, "bob", "alice").json()["error"]["code"] == "already_linked"
    assert link(client, "alice", "alice").json()["error"]["code"] == "invalid_recipient"
    assert link(client, "alice", "ghost").status_code == 404
    resp = link(client, "alice", "operator")
    assert resp.status_code == 403
    assert "operator needs no links" in resp.json()["error"]["message"]
    client.delete("/api/agents/bob")  # bob's line is archived with him
    resp = link(client, "alice", "bob")
    assert resp.json()["error"]["code"] == "agent_gone"


# -- unlink ----------------------------------------------------------------------------


def test_unlink_archives_the_history_and_removes_the_permission(client, make_agent):
    _, alice = make_agent("alice")
    make_agent("bob")
    set_discovery(client, "manual")
    line_id = link(client, "alice", "bob").json()["id"]
    message = send(client, alice, "bob", "kept for the record").json()

    resp = client.post(f"/api/lines/{line_id}/unlink")
    assert resp.status_code == 200, resp.text
    archive = resp.json()
    assert archive["reason"] == "unlinked" and archive["message_count"] == 1
    assert client.get(f"/api/lines/{line_id}").status_code == 404
    assert send(client, alice, "bob").json()["error"]["code"] == "not_linked"

    transcript = client.get(f"/api/archive/{archive['id']}").json()["transcript"]
    assert [m["id"] for m in transcript] == [message["id"]]


def test_unlink_refuses_operator_lines_and_unknown_lines(client, make_agent):
    make_agent("alice")
    client.post("/api/operator/send", json={"to": "alice", "body": "hi"})
    line = client.get("/api/lines").json()[0]
    resp = client.post(f"/api/lines/{line['id']}/unlink")
    assert resp.status_code == 403
    assert client.post("/api/lines/00000000-0000-0000-0000-000000000000/unlink").status_code == 404


# -- discovery follows the lines (peers + attach roster) -------------------------------


def test_peers_and_attach_roster_narrow_to_linked_under_manual(client, make_agent):
    _, alice = make_agent("alice")
    make_agent("bob")
    make_agent("carol")

    view = peers_of(client, "alice", alice)
    assert {p["name"] for p in view["peers"]} == {"bob", "carol", "operator"}

    set_discovery(client, "manual")
    view = peers_of(client, "alice", alice)  # no links yet: only the operator remains
    assert {p["name"] for p in view["peers"]} == {"operator"}

    link(client, "alice", "bob")
    view = peers_of(client, "alice", alice)
    assert {p["name"] for p in view["peers"]} == {"bob", "operator"}
    assert "the operator manages the links" in view["rendered"]

    summary = attach(client, "alice", alice).json()
    assert {p["name"] for p in summary["roster"]} == {"bob", "operator"}

    set_discovery(client, "auto")
    view = peers_of(client, "alice", alice)
    assert {p["name"] for p in view["peers"]} == {"bob", "carol", "operator"}
