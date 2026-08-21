"""Registry API: invite, resolve, tokens, removal, operator bootstrap, peer discovery."""

from conftest import auth
from courtyard.hub.core.peers import PEER_LIMIT, render


def test_operator_autocreated_on_startup(client):
    agents = {a["name"]: a for a in client.get("/api/agents").json()}
    assert agents["operator"]["type"] == "human"


def test_create_get_by_name_and_id(client, make_agent):
    agent, token = make_agent("alice")
    assert token
    assert client.get("/api/agents/alice").json()["id"] == agent["id"]
    assert client.get(f"/api/agents/{agent['id']}").json()["name"] == "alice"


def test_description_round_trip(client):
    resp = client.post(
        "/api/agents",
        json={"name": "infra", "type": "puppet", "description": "terraform, k8s, home-lab DNS"},
    )
    assert resp.status_code == 201
    assert resp.json()["agent"]["description"] == "terraform, k8s, home-lab DNS"
    listed = {a["name"]: a for a in client.get("/api/agents").json()}
    assert listed["infra"]["description"] == "terraform, k8s, home-lab DNS"
    assert listed["operator"]["description"] == "the human operator of this courtyard"


def test_tokens_never_appear_in_listings(client, make_agent):
    make_agent("alice")
    for listed in client.get("/api/agents").json():
        assert "token" not in listed and "token_hash" not in listed


def test_duplicate_name_refused(client, make_agent):
    make_agent("alice")
    resp = client.post("/api/agents", json={"name": "alice", "type": "puppet"})
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "name_taken"


def test_invalid_name_rejected(client):
    resp = client.post("/api/agents", json={"name": "bad name!", "type": "puppet"})
    assert resp.status_code == 422


def test_unknown_agent_hard_fails(client):
    resp = client.get("/api/agents/nobody")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "unknown_agent"


def test_remove_marks_gone_and_keeps_history(client, make_agent):
    make_agent("alice")
    assert client.delete("/api/agents/alice").json()["status"] == "gone"
    assert client.get("/api/agents/alice").json()["status"] == "gone"


def test_operator_cannot_be_removed(client):
    resp = client.delete("/api/agents/operator")
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "cannot_remove_operator"


def test_inbox_requires_the_agents_own_token(client, make_agent):
    _, alice_token = make_agent("alice")
    _, bob_token = make_agent("bob")
    assert client.get("/api/agents/alice/inbox").status_code == 401
    assert client.get("/api/agents/alice/inbox", headers=auth("junk")).status_code == 401
    assert client.get("/api/agents/alice/inbox", headers=auth(bob_token)).status_code == 403
    assert client.get("/api/agents/alice/inbox", headers=auth(alice_token)).status_code == 200


def test_removed_agents_token_is_revoked(client, make_agent):
    _, token = make_agent("alice")
    client.delete("/api/agents/alice")
    assert client.get("/api/agents/alice/inbox", headers=auth(token)).status_code == 401


def test_sme_domain_is_registered_and_listed(client):
    """The domain of responsibility drives authority grading (design §7.5); it is a
    separate declaration from `description`, which is prose for discovery."""
    resp = client.post(
        "/api/agents",
        json={
            "name": "infra",
            "type": "puppet",
            "description": "the infrastructure agent",
            "sme_domain": "the AWS estate and IAM",
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["agent"]["sme_domain"] == "the AWS estate and IAM"
    assert client.get("/api/agents/infra").json()["sme_domain"] == "the AWS estate and IAM"

    # ownership is optional: an agent may be described without owning anything
    plain = client.post("/api/agents", json={"name": "scout", "type": "puppet"})
    assert plain.json()["agent"]["sme_domain"] is None


# -- peers: discovery ranked, trimmed and worded by the hub (design §7.1, D14) ----------

DEAD_ENDPOINT = "http://127.0.0.1:9/"  # discard port: attach wants a local URL, not a listener


def peers_of(client, name, token):
    return client.get(f"/api/agents/{name}/peers", headers=auth(token))


def test_peers_requires_the_agents_own_token(client, make_agent):
    _, alice = make_agent("alice")
    _, bob = make_agent("bob")
    assert client.get("/api/agents/alice/peers").status_code == 401
    assert peers_of(client, "alice", bob).status_code == 403
    assert peers_of(client, "alice", alice).status_code == 200


def test_peers_excludes_self_and_removed_and_ranks_reachable_first(client, make_agent):
    _, alice = make_agent("alice")
    make_agent("bob", description="deploys things")
    _, carol = make_agent("carol")
    make_agent("dave")
    client.delete("/api/agents/dave")
    client.post(
        "/api/agents/carol/attach",
        json={"endpoint": DEAD_ENDPOINT, "channel_token": "ct"},
        headers=auth(carol),
    )
    client.post(
        "/api/agents", json={"name": "infra", "type": "puppet", "sme_domain": "the AWS estate"}
    )

    view = peers_of(client, "alice", alice).json()
    names = [p["name"] for p in view["peers"]]
    assert names == ["carol", "bob", "infra", "operator"]  # connected first, then by name
    assert view["total"] == 4
    lines = view["rendered"].splitlines()
    assert lines[0].startswith("Agents on the courtyard board")
    assert lines[1].startswith("carol — puppet, connected")
    assert "bob — puppet, invited — deploys things" in lines
    assert "infra — puppet, invited — owns: the AWS estate" in lines
    assert "more registrations" not in view["rendered"]


def test_peers_trims_the_long_tail_and_says_so(client, make_agent):
    _, alice = make_agent("alice")
    for i in range(PEER_LIMIT + 4):
        make_agent(f"old-{i:02d}")
    view = peers_of(client, "alice", alice).json()
    assert len(view["peers"]) == PEER_LIMIT
    assert view["total"] == PEER_LIMIT + 5  # the tail plus the operator
    assert view["rendered"].splitlines()[-1] == (
        "(and 5 more registrations that have not been active)"
    )


def test_peers_wording_when_alone():
    assert render([], 0) == "You are the only agent on this courtyard board."
