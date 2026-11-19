import json
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi.testclient import TestClient
from fairy.app import create_app
from fairy.store import Store
from fairy.service import Service
from fairy.worker import tick
from fairy.cognition import rrf, decay, shallow_score, context
from tests.db import postgres_url


@pytest.fixture
def app(tmp_path):
    return create_app(postgres_url(tmp_path), token="test-secret")


@pytest.fixture
def client(app):
    c = TestClient(app)
    c.headers["Authorization"] = "Bearer test-secret"
    return c


def post(c, path, body, key="k"):
    return c.post("/v2/" + path, json=body, headers={"Idempotency-Key": key})


def test_auth(app):
    c = TestClient(app)
    assert c.get("/healthz").status_code == 200
    assert c.get("/v2/cards").status_code == 401
    assert c.get("/").status_code == 200


def test_fail_closed(tmp_path):
    c = TestClient(create_app(postgres_url(tmp_path), token=""))
    assert c.get("/v2/cards").status_code == 503


def test_turn_idempotency_and_no_fake_model(client):
    r = post(client, "turns", {"text": "你好"}).json()
    assert r["status"] == "failed" and r["error"] == "model_not_configured"
    assert post(client, "turns", {"text": "你好"}).json()["id"] == r["id"]
    assert post(client, "turns", {"text": "不同"}).status_code == 409
    assert len(client.get("/v2/turns").json()) == 1
    assert client.get("/v2/memories").json() == []


def test_scope_cannot_be_spoofed(client):
    assert (
        post(client, "turns", {"text": "x", "scope_id": "someone"}).status_code == 422
    )


def test_pending_turn_is_unique(app):
    svc = app.state.service
    r = svc.start_turn("a", "1")
    assert svc.start_turn("a", "1")["_replayed"]
    with pytest.raises(Exception):
        svc.start_turn("b", "2")
    svc.cancel(r["id"])
    assert svc.start_turn("b", "2")["status"] == "pending"


def test_deleted_evidence_cascades(app, client):
    svc = app.state.service
    t = svc.start_turn("我喜欢喝茶", "t")
    svc.cancel(t["id"])
    m = post(
        client,
        "memories",
        {"text": "我喜欢喝茶", "source_ids": [t["evidence_id"]]},
        "m",
    ).json()
    assert client.get("/v2/memories?q=喝茶").json()["results"]
    assert (
        post(
            client,
            "memories",
            {"text": "我喜欢咖啡", "source_ids": [t["evidence_id"]]},
            "bad",
        ).status_code
        == 422
    )
    assert (
        client.delete("/v2/records/" + t["evidence_id"] + "?revision=1").status_code
        == 200
    )
    assert client.get("/v2/memories?q=喝茶").json()["results"] == []
    assert client.get("/v2/memories").json() == []
    assert (
        client.delete("/v2/records/" + t["evidence_id"] + "?revision=1").status_code
        == 409
    )


def test_principal_denial(app):
    assert (
        app.state.service.recall("private", "unknown")["reason"]
        == "private_recall_denied"
    )


def test_learning_and_acquired_skill(app, client):
    result = post(
        client,
        "learning/materials",
        {"title": "植物", "text": "叶片通过光合作用制造养分。"},
    ).json()
    id = result["course"]["id"]
    assert (
        post(client, "skills/acquired?course_id=" + id, {}, "early").status_code == 409
    )
    assert tick(app.state.db)
    assert not tick(app.state.db)
    course = client.get("/v2/learning/courses").json()[0]
    assert not course["mastered"] and course["stage"] == "awaiting_assessment"
    assert (
        client.post(
            "/v2/learning/courses/" + id + "/assess",
            json={"revision": 1, "passed": True, "evidence": "演示"},
        ).status_code
        == 409
    )
    check = client.post(
        "/v2/learning/courses/" + id + "/assess",
        json={
            "revision": course["revision"],
            "passed": True,
            "evidence": "已用新问题验证正确",
        },
    ).json()
    assert check["mastered"]
    skill = post(client, "skills/acquired?course_id=" + id, {}, "acquire").json()
    assert skill["executable"] is False
    assert len(client.get("/v2/skills").json()) == 1
    client.delete("/v2/records/" + result["material"]["id"] + "?revision=1")
    assert not client.get("/v2/skills").json()


def test_delete_before_worker(app, client):
    r = post(client, "learning/materials", {"title": "t", "text": "x"}).json()
    client.delete("/v2/records/" + r["material"]["id"] + "?revision=1")
    assert not tick(app.state.db)
    assert not client.get("/v2/learning/courses").json()


def test_custom_cards_cannot_grant_permissions(client):
    assert (
        post(
            client, "cards", {"title": "x", "text": "x", "subtype": "approval"}
        ).status_code
        == 422
    )
    r = post(client, "cards", {"title": "备忘", "text": "你好"}).json()
    assert r["action_authority"] is False
    assert (
        post(client, "cards", {"title": "备忘", "text": "你好"}).json()["id"] == r["id"]
    )


def test_timezone_required(client):
    assert (
        post(
            client,
            "cards",
            {
                "title": "提醒",
                "text": "x",
                "subtype": "reminder",
                "remind_at": "2026-11-20T10:00:00",
            },
        ).status_code
        == 422
    )


def test_config_cas_and_disabled_capabilities(client):
    r = client.put("/v2/config", json={"revision": 0, "daily_minutes": 20}).json()
    assert r["revision"] == 1
    assert client.put("/v2/config", json={"revision": 0}).status_code == 409
    assert (
        client.put("/v2/config", json={"revision": 1, "mac_execute": True}).status_code
        == 422
    )
    assert client.post("/v2/mac/runs").status_code == 501
    assert client.post("/v2/calls").status_code == 501


def test_events_replay_order(client):
    post(client, "cards", {"title": "1", "text": "x"}, "1")
    post(client, "cards", {"title": "2", "text": "x"}, "2")
    events = client.get("/v2/events").json()
    assert events[0]["seq"] < events[1]["seq"]
    assert len(client.get("/v2/events?after=" + str(events[0]["seq"])).json()) == 1


def test_restart_persistence(tmp_path):
    url = postgres_url(tmp_path)
    one = Service(Store(url))
    one.custom_card("hello", "world", "note", None, "a")
    two = Service(Store(url))
    assert two.list("card")[0]["text"] == "world"


def test_concurrent_duplicate_writes(app):
    svc = app.state.service
    with ThreadPoolExecutor(2) as p:
        results = list(
            p.map(lambda _: svc.custom_card("x", "y", "note", None, "same"), range(2))
        )
    assert results[0]["id"] == results[1]["id"]
    assert len(svc.list("card")) == 1


def test_pure_policies():
    assert rrf(["a", "b"], ["b"]) == ["b", "a"]
    assert decay(1, 0, 12) == 0.5
    assert shallow_score(0.8, 2, 0) > shallow_score(0.8, 2, 90)
    with pytest.raises(ValueError):
        context({"identity": ["hello"]}, 2, len)
    assert (
        context({"identity": ["a"], "memory": ["long", "b"]}, 2, len)["omissions"] == 1
    )


def test_deleted_sources_cannot_reappear_in_idempotent_result(app, client):
    body = {"title": "secret", "text": "private original"}
    r = post(client, "learning/materials", body, "mat").json()
    client.delete("/v2/records/" + r["material"]["id"] + "?revision=1")
    replay = post(client, "learning/materials", body, "mat").json()
    assert "text" not in replay["material"]
    assert replay["course"]["status"] == "invalidated"


def test_budget_zero_stops_worker(app, client):
    client.put("/v2/config", json={"revision": 0, "daily_minutes": 0})
    post(client, "learning/materials", {"title": "t", "text": "data"}, "mat")
    assert tick(app.state.db) is False


def test_approval_cas_and_idempotent_execution(app, client):
    r = post(client, "approvals", {"title": "note", "text": "hello"}, "propose").json()
    body = {
        "revision": r["revision"],
        "action_digest": r["digest"],
        "choice": "allow_once",
    }
    assert not client.get("/v2/notes").json()
    first = post(client, "approvals/" + r["id"] + "/choices", body, "approve").json()
    assert first["decision"] == "allow_once"
    assert (
        post(client, "approvals/" + r["id"] + "/choices", body, "approve").json()[
            "artifact_id"
        ]
        == first["artifact_id"]
    )
    assert (
        post(
            client, "approvals/" + r["id"] + "/choices", body, "other-device"
        ).status_code
        == 409
    )
    assert len(client.get("/v2/notes").json()) == 1


def test_approval_digest_and_expiry(app, client):
    from datetime import datetime, timezone, timedelta

    r = post(client, "approvals", {"title": "n", "text": "x"}, "propose").json()
    body = {"revision": r["revision"], "action_digest": "wrong", "choice": "allow_once"}
    assert (
        post(client, "approvals/" + r["id"] + "/choices", body, "wrong").status_code
        == 409
    )
    with app.state.db.tx() as s:
        row = app.state.service.get(s, r["id"])
        d = json.loads(row.payload)
        d["expires_at"] = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        ).isoformat()
        row.payload = json.dumps(d)
    body["action_digest"] = r["digest"]
    assert (
        post(client, "approvals/" + r["id"] + "/choices", body, "expired").status_code
        == 409
    )
    assert not client.get("/v2/notes").json()


def test_provider_context_and_success(tmp_path, monkeypatch):
    import httpx

    monkeypatch.setenv("FAIRY_OLLAMA_MODEL", "fixture")
    seen = []

    def handler(req):
        seen.append(json.loads(req.content))
        return httpx.Response(
            200,
            json={
                "done": True,
                "message": {
                    "content": json.dumps(
                        {
                            "reply": "我记得你喜欢茶。",
                            "outcome": "answered",
                            "escalation_reason": "none",
                            "memories": [],
                        }
                    )
                },
            },
        )

    app = create_app(
        postgres_url(tmp_path),
        token="t",
        transport=httpx.MockTransport(handler),
    )
    c = TestClient(app)
    c.headers["Authorization"] = "Bearer t"
    mat = post(
        c, "learning/materials", {"title": "偏好", "text": "我喜欢喝茶"}, "mat"
    ).json()["material"]
    post(c, "memories", {"text": "我喜欢喝茶", "source_ids": [mat["id"]]}, "mem")
    r = post(c, "turns", {"text": "我喜欢喝茶吗"}, "turn").json()
    assert r["status"] == "completed" and r["reply"] == "我记得你喜欢茶。"
    assert "我喜欢喝茶" in seen[0]["messages"][1]["content"]
    post(c, "turns", {"text": "我喜欢喝茶吗"}, "turn")
    assert len(seen) == 1
    assert not any(x["type"] == "action.executed" for x in c.get("/v2/events").json())


def test_inflight_source_deletion_rejects_reply(app):
    svc = app.state.service
    mat = svc.material("偏好", "我喜欢喝茶", "mat")["material"]
    svc.memory("我喜欢喝茶", [mat["id"]], "m")
    _, snapshot = svc.model_context("喝茶")
    turn = svc.start_turn("喝茶吗", "t")
    svc.invalidate(mat["id"], 1)
    result = svc.finish_turn(turn["id"], text="stale answer", snapshot=snapshot)
    assert result["error"] == "context_snapshot_invalidated" and result["reply"] is None


def test_delete_pending_evidence_removes_transcript_and_late_commit(app):
    svc = app.state.service
    t = svc.start_turn("secret text", "t")
    svc.invalidate(t["evidence_id"], 1)
    assert svc.finish_turn(t["id"], text="late")["status"] == "invalidated"
    assert not svc.list("turn")
    assert "text" not in svc.start_turn("secret text", "t")


def test_local_boundary(client):
    assert (
        client.get("/v2/cards", headers={"Host": "attacker.example"}).status_code == 421
    )
    assert (
        client.get(
            "/v2/cards", headers={"Origin": "https://attacker.example"}
        ).status_code
        == 403
    )
    assert (
        "frame-ancestors 'none'" in client.get("/").headers["content-security-policy"]
    )


def test_mac_config_is_inert(client):
    r = client.put(
        "/v2/config",
        json={
            "revision": 0,
            "mac_allowed_apps": ["com.apple.TextEdit"],
            "mac_allowed_paths": ["/tmp/Fairy"],
        },
    )
    assert r.status_code == 200 and r.json()["mac_execute"] is False
    assert client.get("/v2/config").json()[0]["mac_allowed_apps"] == [
        "com.apple.TextEdit"
    ]
    assert client.post("/v2/mac/runs").status_code == 501
