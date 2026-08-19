def test_health_ok(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["db"] == "ok"


def test_health_reports_db_failure(client):
    async def broken_ping():
        raise RuntimeError("db is down")

    client.app.state.db_ping = broken_ping
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["db"].startswith("error:")


def test_webui_placeholder_served(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Agent Courtyard" in resp.text
