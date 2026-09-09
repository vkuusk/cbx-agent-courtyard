"""Hub memory, slice 1 (design hub-memory.md): the case file and recall.

The hub remembers collaboration, not craft: a thread that closes becomes one case file,
assembled from what the hub already holds (no model call). Recall is the pull path back
into an agent's context: bounded, trimmed, ranked with the participants' declared domains,
filtered by what the asking agent may see, rendered by the hub.
"""

from __future__ import annotations

from conftest import auth
from courtyard.hub.core import memory as memory_core


def send(client, token, to, body, new_thread=False):
    resp = client.post(
        "/api/lines/send",
        json={"to": to, "body": body, "new_thread": new_thread},
        headers=auth(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def decide(client, message_id, verdict, note=None):
    resp = client.post(f"/api/gate/{message_id}", json={"verdict": verdict, "note": note})
    assert resp.status_code == 200, resp.text
    return resp.json()


def pull(client, name, token):
    return client.get(f"/api/agents/{name}/inbox", headers=auth(token)).json()


def close_thread(client, token, peer):
    resp = client.post("/api/lines/close-thread", json={"peer": peer}, headers=auth(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def register(client, name, sme_domain=None, description=None):
    resp = client.post(
        "/api/agents",
        json={"name": name, "type": "dummy", "description": description, "sme_domain": sme_domain},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["agent"], resp.json()["token"]


def settle(client, make_agent=None, *, asker, answerer, ask, answer, returned_first=None):
    """One full exchange on a supervised line: asker asks, (optionally a first draft of
    the answer is returned with a comment,) the answer is approved, the asker closes."""
    a_name, a_tok = asker
    b_name, b_tok = answerer
    q = send(client, a_tok, b_name, ask, new_thread=True)
    decide(client, q["id"], "approve")
    pull(client, b_name, b_tok)
    if returned_first:
        draft_body, comment = returned_first
        draft = send(client, b_tok, a_name, draft_body)
        decide(client, draft["id"], "return", comment)
        pull(client, b_name, b_tok)  # the return notice
    reply = send(client, b_tok, a_name, answer)
    decide(client, reply["id"], "approve", "fine")
    pull(client, a_name, a_tok)
    return close_thread(client, a_tok, b_name)


class TestTheCaseFile:
    def test_closing_a_thread_writes_one_case_file(self, client):
        infra = register(client, "infra", sme_domain="the AWS estate")
        tf = register(client, "tf", sme_domain="terraform modules")
        thread = settle(
            client,
            asker=("infra", infra[1]),
            answerer=("tf", tf[1]),
            ask="does the vpc module support ipv6?",
            answer="yes since v3; set enable_ipv6 = true",
            returned_first=("no idea", "look it up in the module before answering"),
        )
        records = client.get("/api/memory").json()
        assert len(records) == 1
        (r,) = records
        assert r["kind"] == "case" and r["thread_id"] == thread["id"]
        names = {p["name"]: p for p in r["participants"]}
        assert set(names) == {"infra", "tf"}
        assert names["infra"]["sme_domain"] == "the AWS estate"
        assert names["tf"]["sme_domain"] == "terraform modules"
        assert r["opened_by_name"] == "infra" and r["closed_at"] is not None
        # the trimmed view: the ask, the resolution (the answer that got through, not the
        # returned draft), the verdicts that carried a comment, the counts
        assert r["ask"] == "does the vpc module support ipv6?"
        assert r["resolution"] == "yes since v3; set enable_ipv6 = true"
        assert r["verdicts"] == [
            "return: look it up in the module before answering",
            "approve: fine",
        ]
        assert (r["message_count"], r["approved"], r["returned"], r["dropped"]) == (3, 2, 1, 0)
        assert r["document"] is None  # listings carry no document

        full = client.get(f"/api/memory/{r['id']}").json()
        bodies = [m["body"] for m in full["document"]["messages"] if m["kind"] == "message"]
        assert bodies == [
            "does the vpc module support ipv6?",
            "no idea",
            "yes since v3; set enable_ipv6 = true",
        ]
        assert full["document"]["closed_by"] == "infra"
        assert client.get("/api/memory/count").json() == {"count": 1}

    def test_only_a_closed_thread_becomes_a_case_file(self, client):
        """Expired (End shift) and locked (budget) threads never got their answer, and
        recording them would skew every later judgement toward asks that failed."""
        _, alice = register(client, "alice")
        _, bob = register(client, "bob")
        q = send(client, alice, "bob", "left open at end of day", new_thread=True)
        decide(client, q["id"], "approve")
        assert client.post("/api/shift/start").status_code == 200
        assert client.post("/api/shift/end", json={"force": True}).status_code == 200
        assert client.get(f"/api/lines/{q['line_id']}/threads").json()[0]["state"] == "expired"
        assert client.get("/api/memory").json() == []

        client.patch("/api/settings", json={"thread_budget": 2})  # q + a spends it
        try:
            q2 = send(client, alice, "bob", "a short exchange", new_thread=True)
            decide(client, q2["id"], "approve")
            pull(client, "bob", bob)
            a2 = send(client, bob, "alice", "answered")  # a reply always passes
            decide(client, a2["id"], "approve")
            pull(client, "alice", alice)
            over = client.post(
                "/api/lines/send",
                json={"to": "bob", "body": "one more thing"},
                headers=auth(alice),
            )
            assert over.status_code == 409 and over.json()["error"]["code"] == "thread_locked"
            states = {t["state"] for t in client.get(f"/api/lines/{q['line_id']}/threads").json()}
            assert "locked" in states
        finally:
            client.patch("/api/settings", json={"thread_budget": 12})
        assert client.get("/api/memory").json() == []

    def test_operator_threads_count_too(self, client):
        """They are where most tasks originate, and they are never gated."""
        _, alice = register(client, "alice")
        resp = client.post("/api/operator/send", json={"to": "alice", "body": "list your files"})
        assert resp.status_code == 201, resp.text
        pull(client, "alice", alice)
        send(client, alice, "operator", "README.md and main.tf")
        assert client.post("/api/operator/close-thread", json={"peer": "alice"}).status_code == 200
        (r,) = client.get("/api/memory").json()
        assert {p["name"] for p in r["participants"]} == {"operator", "alice"}
        assert r["ask"] == "list your files" and r["resolution"] == "README.md and main.tf"
        assert r["opened_by_name"] == "operator"


class TestRecall:
    def seed(self, client):
        infra = register(client, "infra", sme_domain="the AWS estate")
        tf = register(client, "tf", sme_domain="terraform modules")
        db = register(client, "db", sme_domain="postgres databases")
        settle(
            client,
            asker=("infra", infra[1]),
            answerer=("tf", tf[1]),
            ask="which module version pins provider 5?",
            answer="the vpc module 3.2 pins aws provider 5",
        )
        settle(
            client,
            asker=("infra", infra[1]),
            answerer=("db", db[1]),
            ask="which version of postgres do we run?",
            answer="postgres 17 everywhere since the migration",
        )
        return infra, tf, db

    def test_full_text_finds_by_words_and_ranks_by_domain(self, client):
        self.seed(client)
        # both case files mention "version"; the participants' declared domains tip it
        hits = client.get("/api/memory", params={"q": "terraform version"}).json()
        assert hits[0]["resolution"].startswith("the vpc module")
        hits = client.get("/api/memory", params={"q": "postgres version"}).json()
        assert hits[0]["resolution"].startswith("postgres 17")
        assert client.get("/api/memory", params={"q": "kubernetes"}).json() == []
        # no question: newest first
        newest_first = [h["resolution"] for h in client.get("/api/memory").json()]
        assert newest_first[0].startswith("postgres 17")

    def test_filters_narrow_before_ranking(self, client):
        self.seed(client)
        only_tf = client.get("/api/memory", params={"participant": "tf"}).json()
        assert [h["resolution"][:7] for h in only_tf] == ["the vpc"]
        line_id = only_tf[0]["line_id"]
        assert len(client.get("/api/memory", params={"line": line_id}).json()) == 1
        assert client.get("/api/memory", params={"since": "2999-01-01T00:00:00Z"}).json() == []
        assert len(client.get("/api/memory", params={"limit": 1}).json()) == 1
        assert client.get("/api/memory", params={"limit": 0}).status_code == 422

    def test_recall_is_bounded_trimmed_and_rendered_for_the_model(self, client):
        infra, tf, _db = self.seed(client)
        client.patch("/api/settings", json={"recall_limit": 1, "recall_trim_chars": 80})
        try:
            view = client.get(
                "/api/agents/infra/recall", params={"q": "version"}, headers=auth(infra[1])
            ).json()
            assert len(view["records"]) == 1
            text = view["rendered"]
            assert text.startswith("1 case file from the team's memory (best match first)")
            assert "courtyard_recall(case=" in text
            assert f"[{view['records'][0]['id']}]" in text
            assert "ask (infra):" in text and "resolution:" in text
            assert "verdict approve: fine" in text

            # the trim: a long ask is cut and marked, the full file is one call away
            long_ask = "does the alb module " + "really " * 30 + "support http2?"
            settle(
                client,
                asker=("infra", infra[1]),
                answerer=("tf", tf[1]),
                ask=long_ask,
                answer="yes",
            )
            view = client.get(
                "/api/agents/infra/recall", params={"q": "alb http2"}, headers=auth(infra[1])
            ).json()
            (r,) = view["records"]
            assert r["trimmed"] is True and len(r["ask"]) <= 80 and r["ask"].endswith("…")
            full = client.get(f"/api/agents/infra/recall/{r['id']}", headers=auth(infra[1])).json()
            assert full["ask"] == long_ask and full["trimmed"] is False
            assert full["rendered"].startswith(f"Case file [{r['id']}]")
            assert (
                ". infra → tf" in full["rendered"]
                and ". tf → infra [approve: fine]" in full["rendered"]
            )
        finally:
            client.patch("/api/settings", json={"recall_limit": 5, "recall_trim_chars": 600})

    def test_nothing_found_is_said_plainly(self, client):
        infra, _, _ = self.seed(client)
        view = client.get(
            "/api/agents/infra/recall", params={"q": "kubernetes"}, headers=auth(infra[1])
        ).json()
        assert view["records"] == [] and "holds nothing matching 'kubernetes'" in view["rendered"]

    def test_recall_needs_the_agents_own_token(self, client):
        _infra, tf, _db = self.seed(client)
        assert client.get("/api/agents/infra/recall").status_code == 401
        resp = client.get("/api/agents/infra/recall", headers=auth(tf[1]))
        assert resp.status_code == 403 and resp.json()["error"]["code"] == "not_allowed"

    def test_under_manual_discovery_an_agent_recalls_only_its_own_lines(self, client):
        """Visibility follows discovery (hub-memory.md section 8): under `manual` an
        agent sees the case files it appears in, the operator sees everything."""
        infra, tf, _db = self.seed(client)
        client.patch("/api/settings", json={"discovery": "manual"})
        try:
            as_tf = client.get(
                "/api/agents/tf/recall", params={"q": "version"}, headers=auth(tf[1])
            ).json()
            assert [r["resolution"][:7] for r in as_tf["records"]] == ["the vpc"]
            as_infra = client.get("/api/agents/infra/recall", headers=auth(infra[1])).json()
            assert len(as_infra["records"]) == 2  # party to both
            db_case = next(
                r
                for r in client.get("/api/memory").json()
                if r["resolution"].startswith("postgres")
            )
            denied = client.get(f"/api/agents/tf/recall/{db_case['id']}", headers=auth(tf[1]))
            assert denied.status_code == 403
            assert len(client.get("/api/memory").json()) == 2  # the operator's door sees all
        finally:
            client.patch("/api/settings", json={"discovery": "auto"})
        as_tf = client.get("/api/agents/tf/recall", headers=auth(tf[1])).json()
        assert len(as_tf["records"]) == 2  # back under auto, the whole team's memory

    def test_settings_are_validated(self, client):
        assert client.patch("/api/settings", json={"recall_limit": 0}).status_code == 422
        assert client.patch("/api/settings", json={"recall_limit": 21}).status_code == 422
        assert client.patch("/api/settings", json={"recall_trim_chars": 10}).status_code == 422
        assert client.patch("/api/settings", json={"recall_limit": 3}).status_code == 200
        assert client.get("/api/settings").json()["recall_limit"] == 3
        client.patch("/api/settings", json={"recall_limit": 5})

    def test_unknown_record_is_a_404(self, client):
        resp = client.get("/api/memory/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404 and resp.json()["error"]["code"] == "memory_not_found"


def test_trim_marks_and_cuts():
    from datetime import UTC, datetime
    from uuid import uuid4

    from courtyard.common.models import MemoryRecord

    record = MemoryRecord(
        id=uuid4(),
        kind="case",
        participants=[],
        created_at=datetime.now(UTC),
        ask="x" * 100,
        resolution="short",
        document={"messages": []},
    )
    trimmed = memory_core.trim(record, 20)
    assert trimmed.trimmed is True and len(trimmed.ask) == 20 and trimmed.ask.endswith("…")
    assert trimmed.resolution == "short" and trimmed.document is None
    assert memory_core.trim(record, 200).trimmed is False
