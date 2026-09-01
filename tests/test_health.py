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


def test_webui_files_always_revalidate(client):
    """The WebUI changes with every edit; a browser must never run a mix of cached modules."""
    resp = client.get("/js/app.js")
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "no-cache"
    assert "cache-control" not in client.get("/api/health").headers or (
        client.get("/api/health").headers.get("cache-control") != "no-cache"
    )


def test_fs_dirs_lists_directories_only_hidden_excluded(client, tmp_path):
    """Item 37: the workdir picker's listing."""
    (tmp_path / "beta").mkdir()
    (tmp_path / "Alpha").mkdir()
    (tmp_path / ".hidden").mkdir()
    (tmp_path / "a-file.txt").write_text("x")
    data = client.get(f"/api/fs/dirs?path={tmp_path}").json()
    assert data["path"] == str(tmp_path)
    assert data["dirs"] == ["Alpha", "beta"]  # case-insensitive sort, no files, no dotdirs
    assert data["parent"] == str(tmp_path.parent)
    assert client.get("/api/fs/dirs").json()["path"]  # no path: the hub user's home
    resp = client.get(f"/api/fs/dirs?path={tmp_path}/a-file.txt")
    assert resp.status_code == 404 or resp.status_code == 400
