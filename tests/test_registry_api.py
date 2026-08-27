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


def test_model_round_trip(client):
    """The declared model (feedback 1, WP-A) is stored and listed; omitted = null."""
    resp = client.post("/api/agents", json={"name": "infra", "type": "puppet", "model": "sonnet"})
    assert resp.status_code == 201
    assert resp.json()["agent"]["model"] == "sonnet"
    listed = {a["name"]: a for a in client.get("/api/agents").json()}
    assert listed["infra"]["model"] == "sonnet"
    assert listed["operator"]["model"] is None


def test_tokens_never_appear_in_listings(client, make_agent):
    make_agent("alice")
    for listed in client.get("/api/agents").json():
        assert "token" not in listed and "token_hash" not in listed


# -- colours: every agent gets one; chosen or least-used ------------------------------


def test_agent_colour_chosen_or_assigned(client, make_agent):
    chosen = client.post("/api/agents", json={"name": "alice", "type": "puppet", "color": "teal"})
    assert chosen.json()["agent"]["color"] == "teal"
    first, _ = make_agent("bob")  # no colour given: the least-used one, palette order on ties
    assert first["color"] == "red"
    second, _ = make_agent("carol")
    assert second["color"] == "orange"
    assert client.get("/api/agents/operator").json()["color"] is None


def test_invalid_colour_rejected(client):
    resp = client.post("/api/agents", json={"name": "alice", "type": "puppet", "color": "beige"})
    assert resp.status_code == 422


# -- stored tokens: retrievable and rotatable (design D19) ---------------------------


def test_token_is_retrievable_again(client, make_agent):
    _, token = make_agent("alice")
    assert client.get("/api/agents/alice/token").json() == {"token": token}


def test_rotate_token_revokes_the_old_one_and_drops_the_session(client, make_agent):
    _, old = make_agent("alice")
    client.post(
        "/api/agents/alice/attach",
        json={"endpoint": DEAD_ENDPOINT, "channel_token": "ct"},
        headers=auth(old),
    )
    assert client.get("/api/agents/alice").json()["status"] == "connected"

    resp = client.post("/api/agents/alice/token")
    assert resp.status_code == 201, resp.text
    new = resp.json()["token"]
    assert new != old
    assert client.get("/api/agents/alice/inbox", headers=auth(old)).status_code == 401
    assert client.get("/api/agents/alice/inbox", headers=auth(new)).status_code == 200
    assert client.get("/api/agents/alice/token").json()["token"] == new
    # its running session can no longer reach the hub: channel dropped, reads as offline
    assert client.get("/api/agents/alice").json()["status"] == "gone"


def test_removed_agent_has_no_token_to_read_or_rotate(client, make_agent):
    make_agent("alice")
    client.delete("/api/agents/alice")
    assert client.get("/api/agents/alice/token").json()["error"]["code"] == "agent_gone"
    assert client.post("/api/agents/alice/token").json()["error"]["code"] == "agent_gone"


def test_registration_from_before_stored_tokens_says_rotate(client, make_agent, config):
    import psycopg

    agent, _ = make_agent("alice")
    with psycopg.connect(config.database_url) as conn:  # what migration 0006 leaves behind
        conn.execute("UPDATE agents SET token = NULL WHERE id = %s", (agent["id"],))
    resp = client.get("/api/agents/alice/token")
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "no_stored_token"
    assert client.post("/api/agents/alice/token").status_code == 201  # rotation gives it one
    assert client.get("/api/agents/alice/token").status_code == 200


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


# -- install: the hub writes .mcp.json into the agent's workdir (design §8/D8, 6d) ------


def test_install_writes_mcp_json_into_the_workdir(client, tmp_path):
    created = client.post(
        "/api/agents",
        json={"name": "coding", "type": "claude-code", "workdir": str(tmp_path)},
    ).json()
    token = created["token"]

    resp = client.post("/api/agents/coding/install", json={"token": token})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    target = tmp_path / ".mcp.json"
    assert body["path"] == str(target)
    assert "do not commit" in body["warning"].lower()

    import json as _json

    env = _json.loads(target.read_text())["mcpServers"]["courtyard"]["env"]
    assert env["COURTYARD_AGENT_NAME"] == "coding"
    assert env["COURTYARD_TOKEN"] == token


def test_install_uses_the_stored_token_when_none_is_given(client, tmp_path):
    created = client.post(
        "/api/agents",
        json={"name": "coding", "type": "claude-code", "workdir": str(tmp_path)},
    ).json()
    resp = client.post("/api/agents/coding/install", json={})
    assert resp.status_code == 200, resp.text
    import json as _json

    env = _json.loads((tmp_path / ".mcp.json").read_text())["mcpServers"]["courtyard"]["env"]
    assert env["COURTYARD_TOKEN"] == created["token"]


def test_install_rejects_a_token_that_is_not_this_agents(client, make_agent, tmp_path):
    client.post(
        "/api/agents", json={"name": "coding", "type": "claude-code", "workdir": str(tmp_path)}
    )
    _, other_token = make_agent("bob")
    resp = client.post("/api/agents/coding/install", json={"token": other_token})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "invalid_token"
    assert not (tmp_path / ".mcp.json").exists()  # nothing written on a bad token


def test_install_without_a_workdir_is_a_clear_error(client):
    created = client.post("/api/agents", json={"name": "coding", "type": "claude-code"}).json()
    resp = client.post("/api/agents/coding/install", json={"token": created["token"]})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "workdir_not_found"


def test_install_then_uninstall_round_trips(client, tmp_path):
    (tmp_path / ".mcp.json").write_text('{"mcpServers": {"other": {"command": "x"}}}')
    created = client.post(
        "/api/agents",
        json={"name": "coding", "type": "claude-code", "workdir": str(tmp_path)},
    ).json()
    client.post("/api/agents/coding/install", json={"token": created["token"]})

    resp = client.post("/api/agents/coding/uninstall", json={})
    assert resp.status_code == 200 and resp.json()["restored_from_backup"] is True
    import json as _json

    assert _json.loads((tmp_path / ".mcp.json").read_text())["mcpServers"] == {
        "other": {"command": "x"}
    }


def test_patch_edits_fields_and_null_clears(client, make_agent):
    """WP-D (item 8): description, owns, workdir, model, colour are editable after
    creation; an explicit null clears; absent keys are untouched."""
    make_agent("scout")
    resp = client.patch(
        "/api/agents/scout",
        json={"description": "recon", "sme_domain": "the network edge", "model": "haiku"},
    )
    assert resp.status_code == 200
    updated = resp.json()
    assert (updated["description"], updated["sme_domain"], updated["model"]) == (
        "recon",
        "the network edge",
        "haiku",
    )
    resp = client.patch("/api/agents/scout", json={"model": None, "color": "teal"})
    assert resp.status_code == 200
    assert resp.json()["model"] is None  # cleared
    assert resp.json()["color"] == "teal"
    assert resp.json()["description"] == "recon"  # untouched


def test_patch_never_edits_identity_or_the_operator(client, make_agent):
    make_agent("scout")
    resp = client.patch("/api/agents/scout", json={"name": "spy"})
    assert resp.status_code == 422  # unknown field for the schema
    resp = client.patch("/api/agents/operator", json={"description": "x"})
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "not_allowed"


def test_patch_refuses_a_removed_agent(client, make_agent):
    make_agent("scout")
    client.delete("/api/agents/scout")
    resp = client.patch("/api/agents/scout", json={"description": "x"})
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "agent_gone"


def test_default_line_mode_applies_to_new_lines_only(client, make_agent):
    """7c: the Admin default sets the dial a NEW line starts on; existing lines keep
    theirs, and operator lines are still never gated."""
    from conftest import auth

    _, alice = make_agent("alice")
    make_agent("bob")
    make_agent("carol")
    first = client.post(
        "/api/lines/send", json={"to": "bob", "body": "q"}, headers=auth(alice)
    ).json()
    assert first["status"] == "pending_gate"  # default default: supervised

    client.patch("/api/settings", json={"default_line_mode": "auto_pass"})
    second = client.post(
        "/api/lines/send", json={"to": "carol", "body": "q"}, headers=auth(alice)
    ).json()
    assert second["status"] == "queued"  # new line follows the new default
    lines = {
        frozenset((ln["agent_a_name"], ln["agent_b_name"])): ln["mode"]
        for ln in client.get("/api/lines").json()
    }
    assert lines[frozenset(("alice", "bob"))] == "supervised"  # existing line untouched
    assert lines[frozenset(("alice", "carol"))] == "auto_pass"
