"""Registry API: invite, resolve, tokens, removal, operator bootstrap."""

from conftest import auth


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
