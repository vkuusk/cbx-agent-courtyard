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
            assert text.startswith("1 record from the team's memory (best match first)")
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


class TestNotes:
    """Slice 2: a note is a memory record with an author, a body and a scope, no thread.
    It is not a message (nobody is addressed, no turn, no answer owed) but it passes the
    gate like one; only accepted notes are memory."""

    def pair(self, client, mode="supervised"):
        infra = register(client, "infra", sme_domain="the AWS estate")
        tf = register(client, "tf", sme_domain="terraform modules")
        q = send(client, infra[1], "tf", "hello", new_thread=True)
        decide(client, q["id"], "approve")
        pull(client, "tf", tf[1])  # drain the hello, so later inboxes hold only notices
        if mode == "auto_pass":
            client.post(f"/api/lines/{q['line_id']}/mode", json={"mode": "auto_pass"})
        return infra, tf, q["line_id"]

    def note(self, client, token, name, body, **fields):
        return client.post(
            f"/api/agents/{name}/notes", json={"body": body, **fields}, headers=auth(token)
        )

    def test_a_note_on_a_supervised_line_waits_for_the_operator(self, client):
        infra, tf, line_id = self.pair(client)
        resp = self.note(client, tf[1], "tf", "pin aws provider 5 in every module", peer="infra")
        assert resp.status_code == 201, resp.text
        note = resp.json()
        assert note["kind"] == "note" and note["status"] == "pending"
        assert note["scope"] == "line" and note["line_id"] == line_id
        assert {p["name"] for p in note["participants"]} == {"infra", "tf"}
        assert note["author_name"] == "tf" and "held for the operator" in note["rendered"]
        # pending: on the operator's list, not in anyone's memory yet
        assert [n["id"] for n in client.get("/api/memory/pending").json()] == [note["id"]]
        assert client.get("/api/memory").json() == []
        view = client.get(
            "/api/agents/infra/recall", params={"q": "provider"}, headers=auth(infra[1])
        ).json()
        assert view["records"] == []
        # the author may still read its own pending note by handle; the peer may not
        assert (
            client.get(f"/api/agents/tf/recall/{note['id']}", headers=auth(tf[1])).status_code
            == 200
        )
        assert (
            client.get(f"/api/agents/infra/recall/{note['id']}", headers=auth(infra[1])).status_code
            == 403
        )

    def test_approve_makes_it_memory_for_the_lines_two_agents_only(self, client):
        infra, tf, _ = self.pair(client)
        argo = register(client, "argo", sme_domain="argocd")
        note = self.note(
            client, tf[1], "tf", "pin aws provider 5 in every module", peer="infra"
        ).json()
        decided = client.post(
            f"/api/memory/{note['id']}/decide", json={"verdict": "approve"}
        ).json()
        assert decided["status"] == "accepted" and decided["decided_at"] is not None
        assert client.get("/api/memory/pending").json() == []
        for name, token in (("infra", infra[1]), ("tf", tf[1])):
            view = client.get(
                f"/api/agents/{name}/recall", params={"q": "provider"}, headers=auth(token)
            ).json()
            assert [r["id"] for r in view["records"]] == [note["id"]]
            assert (
                "note by tf (for infra ↔ tf)" in view["rendered"]
                or "note by tf (for tf ↔ infra)" in view["rendered"]
            )
            assert "pin aws provider 5" in view["rendered"]
        view = client.get(
            "/api/agents/argo/recall", params={"q": "provider"}, headers=auth(argo[1])
        ).json()
        assert view["records"] == []  # a line's note reaches that line's agents only
        assert (
            client.get(f"/api/agents/argo/recall/{note['id']}", headers=auth(argo[1])).status_code
            == 403
        )
        # the operator's door sees it, and the full record renders as a note
        (r,) = client.get("/api/memory").json()
        assert r["kind"] == "note" and r["body"] == "pin aws provider 5 in every module"
        full = client.get(f"/api/agents/tf/recall/{note['id']}", headers=auth(tf[1])).json()
        assert full["rendered"].startswith(f"Note [{note['id']}] by tf, for ")
        # approve is silent: nothing landed on the author's operator line
        assert pull(client, "tf", tf[1]) == []

    def test_return_and_drop_tell_the_author_on_the_operators_line(self, client):
        _infra, tf, _ = self.pair(client)
        first = self.note(client, tf[1], "tf", "always use latest", peer="infra").json()
        returned = client.post(
            f"/api/memory/{first['id']}/decide",
            json={"verdict": "return", "note": "too vague: which module, which version?"},
        ).json()
        assert returned["status"] == "returned" and returned["gate_note"].startswith("too vague")
        notices = pull(client, "tf", tf[1])
        assert len(notices) == 1 and notices[0]["kind"] == "system"
        assert "was returned to you" in notices[0]["body"]
        assert "Operator's comment: too vague" in notices[0]["body"]
        assert notices[0]["sender_name"] is None and notices[0]["recipient_name"] == "tf"

        second = self.note(client, tf[1], "tf", "delete prod first", peer="infra").json()
        dropped = client.post(f"/api/memory/{second['id']}/decide", json={"verdict": "drop"}).json()
        assert dropped["status"] == "dropped"
        (notice,) = pull(client, "tf", tf[1])
        assert "dropped (do not resend it)" in notice["body"]
        # neither is memory; a second verdict on the same note is refused
        assert client.get("/api/memory").json() == []
        again = client.post(f"/api/memory/{second['id']}/decide", json={"verdict": "approve"})
        assert again.status_code == 409 and again.json()["error"]["code"] == "note_not_pending"

    def test_auto_pass_lines_take_notes_without_the_gate(self, client):
        _infra, tf, _ = self.pair(client, mode="auto_pass")
        note = self.note(client, tf[1], "tf", "module 3.2 is the floor", peer="infra").json()
        assert note["status"] == "accepted" and "Noted and remembered" in note["rendered"]
        assert client.get("/api/memory/pending").json() == []
        assert len(client.get("/api/memory").json()) == 1

    def test_team_wide_notes_always_wait_and_then_reach_everyone(self, client):
        _infra, tf, _ = self.pair(client, mode="auto_pass")
        argo = register(client, "argo")
        note = self.note(
            client, tf[1], "tf", "we never force-push shared branches", team_wide=True
        ).json()
        assert note["status"] == "pending" and note["scope"] == "team"
        client.post(f"/api/memory/{note['id']}/decide", json={"verdict": "approve"})
        client.patch("/api/settings", json={"discovery": "manual"})
        try:
            view = client.get("/api/agents/argo/recall", headers=auth(argo[1])).json()
            assert [r["id"] for r in view["records"]] == [note["id"]]  # not party to any line
            assert "note by tf (team-wide)" in view["rendered"]
        finally:
            client.patch("/api/settings", json={"discovery": "auto"})

    def test_the_only_line_is_the_default_scope_otherwise_the_agent_must_say(self, client):
        _infra, tf, line_id = self.pair(client, mode="auto_pass")
        note = self.note(client, tf[1], "tf", "one line, no peer needed").json()
        assert note.get("line_id") == line_id
        argo = register(client, "argo")
        q = send(client, argo[1], "tf", "hi", new_thread=True)
        decide(client, q["id"], "approve")
        resp = self.note(client, tf[1], "tf", "two lines now")
        assert resp.status_code == 422 and resp.json()["error"]["code"] == "note_scope_unclear"
        resp = self.note(client, tf[1], "tf", "with nobody", peer="operator")
        assert resp.status_code == 404  # no line with the operator yet
        lonely = register(client, "lonely")
        resp = self.note(client, lonely[1], "lonely", "nobody talks to me")
        assert resp.status_code == 422 and "team_wide" in resp.json()["error"]["message"]
        assert self.note(client, tf[1], "tf", "   ").status_code == 422
        assert self.note(client, tf[1], "tf", "x" * 2001, team_wide=True).status_code == 422

    def test_the_operators_note_is_accepted_at_once(self, client):
        _infra, tf, line_id = self.pair(client)
        team = client.post("/api/memory/notes", json={"body": "ask before deleting anything"})
        assert team.status_code == 201, team.text
        assert team.json()["status"] == "accepted" and team.json()["scope"] == "team"
        assert team.json()["author_name"] == "operator"
        scoped = client.post(
            "/api/memory/notes",
            json={"body": "this pair uses semver", "scope": "line", "line": line_id},
        ).json()
        assert scoped["scope"] == "line" and {p["name"] for p in scoped["participants"]} == {
            "infra",
            "tf",
        }
        assert (
            client.post("/api/memory/notes", json={"body": "x", "scope": "line"}).status_code == 422
        )
        view = client.get("/api/agents/tf/recall", headers=auth(tf[1])).json()
        assert {r["body"] for r in view["records"]} == {
            "ask before deleting anything",
            "this pair uses semver",
        }

    def test_the_envelope_preview_shows_a_recall_listing(self, client):
        blocks = {b["title"]: b for b in client.get("/api/envelope").json()}
        block = blocks["A recall listing"]
        assert "2 records from the team's memory" in block["text"]
        assert "note by tf-agent" in block["text"] and block["overhead_tokens"] > 0
