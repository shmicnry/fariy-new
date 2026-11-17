import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from fairy.app import create_app
from fairy.model_settings import ModelConfig
from fairy.models import LocalAnswer
from fairy.store import Record


def local(reply="本地回答", outcome="answered", reason="none", memories=None):
    return httpx.Response(
        200,
        json={
            "done": True,
            "done_reason": "stop",
            "message": {
                "content": json.dumps(
                    {
                        "reply": reply,
                        "outcome": outcome,
                        "escalation_reason": reason,
                        "memories": memories or [],
                    },
                    ensure_ascii=False,
                )
            },
            "prompt_eval_count": 20,
            "eval_count": 10,
        },
    )


def cloud(reply="云端回答"):
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": reply}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 30, "completion_tokens": 10},
        },
    )


@pytest.fixture
def factory(tmp_path, monkeypatch):
    monkeypatch.setenv("FAIRY_OLLAMA_MODEL", "fixture")
    count = [0]

    def make(handler=None):
        count[0] += 1
        app = create_app(
            "sqlite:///" + str(tmp_path / (str(count[0]) + ".db")),
            token="test",
            transport=httpx.MockTransport(handler or (lambda req: local())),
        )
        c = TestClient(app)
        c.headers["Authorization"] = "Bearer test"
        return app, c

    return make


def post(c, path, data, key="request"):
    return c.post("/v2/" + path, json=data, headers={"Idempotency-Key": key})


def enable(c, **extra):
    current = c.get("/v2/models/config").json()
    payload = {k: v for k, v in current.items() if k in ModelConfig.model_fields}
    payload.update(
        cloud_enabled=True,
        cloud_base_url="https://provider.test/v1",
        cloud_model="cloud-fixture",
        cloud_api_key="unit-test-key-never-real",
    )
    payload.update(extra)
    r = c.put("/v2/models/config", json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def material(c, text="我喜欢喝茶"):
    return post(
        c,
        "learning/materials",
        {"title": "测试来源", "text": text},
        "material-" + text.encode().hex(),
    ).json()["material"]


def saved_memory(c, text="我喜欢喝茶"):
    source = material(c, text)
    return post(
        c,
        "memories",
        {"text": text, "source_ids": [source["id"]]},
        "memory-" + text.encode().hex(),
    ).json()


def correction(c, memory, text="我现在喜欢喝咖啡", key="correction"):
    return c.patch(
        "/v2/memories/" + memory["id"],
        json={"revision": memory["revision"], "text": text, "reason": "用户明确更正"},
        headers={"Idempotency-Key": key},
    )


def test_local_native_and_no_unnecessary_cloud(factory):
    seen = []

    def handler(req):
        seen.append(req)
        return local()

    app, c = factory(handler)
    enable(c)
    r = post(c, "turns", {"text": "你好"}).json()
    assert r["reply"] == "本地回答" and not r["model_route"]["cloud_used"]
    assert [req.url.path for req in seen] == ["/api/chat"]
    request = json.loads(seen[0].content)
    assert request["stream"] is False and request["format"]["type"] == "object"
    assert c.get("/v2/models/invocations").json()[0]["status"] == "succeeded"


def test_local_needs_cloud_escalates_once_and_is_idempotent(factory):
    seen = []

    def handler(req):
        seen.append(req)
        return (
            local("需要更强模型帮助", "needs_cloud", "capability_limit")
            if req.url.host == "127.0.0.1"
            else cloud()
        )

    app, c = factory(handler)
    enable(c)
    first = post(c, "turns", {"text": "复杂问题"}).json()
    assert first["reply"] == "云端回答" and first["model_route"]["cloud_used"]
    assert first["model_route"]["escalation_reason"] == "capability_limit"
    assert len(seen) == 2
    assert (
        post(c, "turns", {"text": "复杂问题"}).json()["id"] == first["id"]
        and len(seen) == 2
    )
    assert (
        post(c, "turns", {"text": "复杂问题", "routing": "local_only"}).status_code
        == 409
    )


def test_local_only_and_disabled_cloud_never_egress(factory):
    seen = []

    def handler(req):
        seen.append(req)
        return local("需要帮助", "needs_cloud", "knowledge_gap")

    app, c = factory(handler)
    r = post(c, "turns", {"text": "问题"}, "a").json()
    assert r["model_route"]["cloud_skip_reason"] == "cloud_disabled"
    enable(c)
    r = post(c, "turns", {"text": "问题", "routing": "local_only"}, "b").json()
    assert r["model_route"]["cloud_skip_reason"] == "local_only"
    assert all(req.url.host == "127.0.0.1" for req in seen)


def test_cloud_default_omits_history_and_memories(factory):
    seen = []

    def handler(req):
        seen.append(req)
        return (
            local("需要帮助", "needs_cloud", "capability_limit")
            if req.url.host == "127.0.0.1"
            else cloud()
        )

    app, c = factory(handler)
    saved_memory(c, "私密爱好是喝茶")
    enable(c)
    t = app.state.service.start_turn("私密历史", "old")
    app.state.service.finish_turn(t["id"], text="私密回答")
    post(c, "turns", {"text": "请推导公式"})
    payload = seen[-1].content.decode()
    assert "私密" not in payload and "请推导公式" in payload
    assert seen[-1].headers["Authorization"] == "Bearer unit-test-key-never-real"


def test_opt_in_cloud_memories_are_explicit_and_bounded(factory):
    seen = []

    def handler(req):
        seen.append(req)
        return (
            local("需要帮助", "needs_cloud", "knowledge_gap")
            if req.url.host == "127.0.0.1"
            else cloud()
        )

    app, c = factory(handler)
    saved_memory(c)
    enable(c, cloud_context="approved_memories")
    post(c, "turns", {"text": "我喜欢喝茶吗"})
    assert "我喜欢喝茶" in seen[-1].content.decode()


@pytest.mark.parametrize("outcome", ["clarification", "refused"])
def test_refusal_and_clarification_do_not_trigger_cloud(factory, outcome):
    seen = []

    def handler(req):
        seen.append(req)
        return local("请补充信息", outcome)

    app, c = factory(handler)
    enable(c)
    post(c, "turns", {"text": "问题", "routing": "cloud_assist"})
    assert len(seen) == 1


def test_manual_cloud_assist_after_local_answer(factory):
    seen = []

    def handler(req):
        seen.append(req)
        return local() if req.url.host == "127.0.0.1" else cloud()

    app, c = factory(handler)
    enable(c)
    r = post(c, "turns", {"text": "问题", "routing": "cloud_assist"}).json()
    assert len(seen) == 2 and r["model_route"]["escalation_reason"] == "user_requested"


@pytest.mark.parametrize("failure", ["unavailable", "timeout", "invalid"])
def test_local_failure_uses_configured_cloud(factory, failure):
    def handler(req):
        if req.url.host != "127.0.0.1":
            return cloud()
        if failure == "unavailable":
            raise httpx.ConnectError("offline", request=req)
        if failure == "timeout":
            raise httpx.ReadTimeout("wait", request=req)
        return httpx.Response(
            200, json={"done": True, "message": {"content": "not JSON"}}
        )

    app, c = factory(handler)
    enable(c)
    r = post(c, "turns", {"text": "问题"}).json()
    assert r["reply"] == "云端回答" and r["model_route"]["cloud_used"]
    calls = c.get("/v2/models/invocations").json()
    assert calls[0]["status"] == ("unknown" if failure == "timeout" else "failed")


def test_cloud_unknown_timeout_is_not_retried(factory):
    seen = []

    def handler(req):
        seen.append(req)
        if req.url.host == "127.0.0.1":
            return local("能力不足", "needs_cloud", "capability_limit")
        raise httpx.ReadTimeout("never include provider details", request=req)

    app, c = factory(handler)
    enable(c)
    a = post(c, "turns", {"text": "问题"}).json()
    post(c, "turns", {"text": "问题"})
    assert len(seen) == 2 and a["model_route"]["cloud_skip_reason"] == "cloud_timeout"
    assert c.get("/v2/models/invocations").json()[-1]["status"] == "unknown"


def test_daily_cloud_request_limit_counts_attempts(factory):
    seen = []

    def handler(req):
        seen.append(req)
        return (
            local("需要帮助", "needs_cloud", "capability_limit")
            if req.url.host == "127.0.0.1"
            else cloud()
        )

    app, c = factory(handler)
    enable(c, cloud_daily_request_limit=1)
    post(c, "turns", {"text": "一"}, "one")
    second = post(c, "turns", {"text": "二"}, "two").json()
    assert second["model_route"]["cloud_skip_reason"] == "cloud_daily_limit_reached"
    assert sum(req.url.host == "provider.test" for req in seen) == 1


def test_model_config_cas_and_credentials_are_write_only(factory):
    app, c = factory()
    r = enable(c)
    assert "unit-test-key" not in json.dumps(r) and r["cloud_key_configured"]
    assert c.put("/v2/models/config", json={"revision": 1}).status_code == 409
    assert "unit-test-key" not in c.get("/v2/events").text
    assert "unit-test-key" not in c.get("/v2/models/invocations").text
    vault = list(app.state.model_settings.vault.directory.glob("*.json"))
    assert len(vault) == 1 and vault[0].stat().st_mode & 0o777 == 0o600
    with app.state.db.sessions() as s:
        assert "unit-test-key" not in app.state.model_settings.record(s).payload
    payload = {k: v for k, v in r.items() if k in ModelConfig.model_fields}
    payload["cloud_base_url"] = "https://other.test/v1"
    assert c.put("/v2/models/config", json=payload).status_code == 422


def test_validation_never_echoes_secret(factory):
    app, c = factory()
    r = c.put(
        "/v2/models/config",
        json={
            "revision": 1,
            "cloud_enabled": True,
            "cloud_api_key": "secret-must-not-echo",
        },
    )
    assert r.status_code == 422 and "secret-must-not-echo" not in r.text
    assert (
        c.put(
            "/v2/models/config",
            json={"revision": 1, "ollama_base_url": "https://external.test"},
        ).status_code
        == 422
    )
    assert (
        c.put(
            "/v2/models/config",
            json={"revision": 1, "cloud_base_url": "http://plain.test/v1"},
        ).status_code
        == 422
    )


def test_installed_models_detection(factory):
    def handler(req):
        return httpx.Response(
            200, json={"models": [{"name": "fixture", "capabilities": ["completion"]}]}
        )

    app, c = factory(handler)
    result = c.get("/v2/models/ollama").json()
    assert result["reachable"] and result["selected_installed"]


def test_auto_proposal_needs_review_and_has_exact_source(factory):
    app, c = factory(
        lambda req: local(
            "我知道了", memories=[{"quote": "我喜欢喝茶", "category": "preference"}]
        )
    )
    r = post(c, "turns", {"text": "我喜欢喝茶"}).json()
    assert c.get("/v2/memories").json() == []
    p = c.get("/v2/memory/proposals").json()[0]
    assert p["id"] in r["memory_proposal_ids"] and p["status"] == "pending"
    assert c.get("/v2/sources/" + p["source_ids"][0]).json()["text"] == "我喜欢喝茶"
    review = {"revision": p["revision"], "decision": "approve"}
    a = post(c, "memory/proposals/" + p["id"] + "/review", review, "approve").json()
    assert (
        post(c, "memory/proposals/" + p["id"] + "/review", review, "approve").json()[
            "memory_id"
        ]
        == a["memory_id"]
    )
    assert (
        post(c, "memory/proposals/" + p["id"] + "/review", review, "other").status_code
        == 409
    )
    assert len(c.get("/v2/memories").json()) == 1
    assert c.get("/v2/memories?q=喝茶").json()["results"]


def test_unquoted_model_candidate_is_discarded(factory):
    app, c = factory(lambda req: local(memories=[{"quote": "我喜欢喝咖啡"}]))
    post(c, "turns", {"text": "我喜欢喝茶"})
    assert c.get("/v2/memory/proposals").json() == []
    assert any(
        e["type"] == "memory.proposal_discarded" for e in c.get("/v2/events").json()
    )


def test_reject_and_memory_off_do_not_save(factory):
    app, c = factory(lambda req: local(memories=[{"quote": "我喜欢喝茶"}]))
    post(c, "turns", {"text": "我喜欢喝茶"})
    p = c.get("/v2/memory/proposals").json()[0]
    post(
        c,
        "memory/proposals/" + p["id"] + "/review",
        {"revision": p["revision"], "decision": "reject"},
        "reject",
    )
    assert not c.get("/v2/memories").json()
    cfg = c.get("/v2/models/config").json()
    data = {k: v for k, v in cfg.items() if k in ModelConfig.model_fields}
    data["memory_mode"] = "off"
    assert c.put("/v2/models/config", json=data).status_code == 200
    post(c, "turns", {"text": "我喜欢喝茶"}, "off")
    assert len(c.get("/v2/memory/proposals").json()) == 1


def test_revision_correction_history_and_latest_recall(factory):
    app, c = factory()
    old = saved_memory(c)
    new = correction(c, old).json()
    assert new["id"] == old["id"] and new["revision"] == old["revision"] + 1
    assert correction(c, old).json()["revision"] == new["revision"]
    assert correction(c, old, key="conflict").status_code == 409
    history = c.get("/v2/memories/" + old["id"] + "/history").json()
    assert [r["text"] for r in history] == ["我喜欢喝茶", "我现在喜欢喝咖啡"]
    assert history[0]["valid_to"] and history[1]["valid_to"] is None
    assert c.get("/v2/memories?q=喝茶").json()["results"] == []
    assert (
        c.get("/v2/memories?q=咖啡").json()["results"][0]["text"] == "我现在喜欢喝咖啡"
    )
    assert (
        c.get("/v2/sources/" + new["source_ids"][0]).json()["source_type"]
        == "owner_correction"
    )


def test_correction_blocks_old_dialogue_and_inflight_reply(factory):
    app, c = factory()
    svc = app.state.service
    t = svc.start_turn("我喜欢喝茶", "t")
    svc.finish_turn(t["id"], text="你喜欢茶")
    m = post(
        c, "memories", {"text": "我喜欢喝茶", "source_ids": [t["evidence_id"]]}, "m"
    ).json()
    context, snapshot = svc.model_context("喝茶")
    active = svc.start_turn("我喜欢什么", "another")
    correction(c, m)
    result = svc.finish_turn(active["id"], text="旧回答", snapshot=snapshot)
    assert result["reply"] is None and result["error"] == "context_snapshot_invalidated"
    context, _ = svc.model_context("咖啡")
    assert "你喜欢茶" not in json.dumps(context, ensure_ascii=False)


def test_forget_erases_versions_caches_and_suppresses_original(factory):
    app, c = factory()
    m = saved_memory(c)
    new = correction(c, m).json()
    assert (
        c.delete(
            "/v2/memories/" + m["id"] + "?revision=" + str(new["revision"])
        ).status_code
        == 200
    )
    assert c.get("/v2/memories").json() == []
    assert c.get("/v2/memories/" + m["id"] + "/history").json() == []
    replay = correction(c, m).json()
    assert "text" not in replay
    assert (
        post(
            c,
            "memory/proposals",
            {"text": new["text"], "source_id": new["source_ids"][0]},
            "again",
        ).status_code
        == 409
    )
    context, _ = app.state.service.model_context("喝茶 咖啡")
    assert context["entries"] == []


def test_delete_source_invalidates_pending_review(factory):
    app, c = factory()
    source = material(c)
    p = post(
        c, "memory/proposals", {"text": "我喜欢喝茶", "source_id": source["id"]}
    ).json()
    c.delete("/v2/records/" + source["id"] + "?revision=1")
    assert (
        post(
            c,
            "memory/proposals/" + p["id"] + "/review",
            {"revision": p["revision"], "decision": "approve"},
            "review",
        ).status_code
        == 409
    )
    assert not c.get("/v2/memories").json()


def test_concurrent_review_has_one_winner(factory):
    app, c = factory()
    source = material(c)
    p = post(
        c, "memory/proposals", {"text": "我喜欢喝茶", "source_id": source["id"]}
    ).json()
    with ThreadPoolExecutor(2) as pool:

        def review(i):
            return post(
                c,
                "memory/proposals/" + p["id"] + "/review",
                {"revision": p["revision"], "decision": "approve"},
                "device-" + str(i),
            ).status_code

        results = list(pool.map(review, range(2)))
    assert sorted(results) == [200, 409] and len(c.get("/v2/memories").json()) == 1


def test_no_cloud_dispatch_after_cancel_or_source_change(factory):
    seen = []
    holder = {}

    def handler(req):
        seen.append(req)
        holder["app"].state.service.cancel(
            holder["app"].state.service.list("turn")[0]["id"]
        )
        return local("需要帮助", "needs_cloud", "capability_limit")

    app, c = factory(handler)
    holder["app"] = app
    enable(c)
    r = post(c, "turns", {"text": "问题"}).json()
    assert r["status"] == "interrupted" and len(seen) == 1


def test_prompt_size_is_checked_without_silent_truncation(factory):
    seen = []

    def handler(req):
        seen.append(req)
        return local()

    app, c = factory(handler)
    r = post(c, "turns", {"text": "长" * 16000}).json()
    assert r["error"] == "local_input_too_large" and not seen


def test_restart_retains_model_config_memory_versions_and_review(factory, tmp_path):
    app, c = factory()
    m = saved_memory(c)
    new = correction(c, m).json()
    enable(c)
    url = str(app.state.db.engine.url)
    restarted = create_app(url, token="test")
    other = TestClient(restarted)
    other.headers["Authorization"] = "Bearer test"
    assert other.get("/v2/models/config").json()["cloud_key_configured"]
    assert other.get("/v2/memories").json()[0]["text"] == new["text"]
    assert len(other.get("/v2/memories/" + m["id"] + "/history").json()) == 2


def test_key_clear_removes_retired_private_file(factory):
    app, c = factory()
    cfg = enable(c)
    directory = app.state.model_settings.vault.directory
    assert len(list(directory.glob("*.json"))) == 1
    payload = {k: v for k, v in cfg.items() if k in ModelConfig.model_fields}
    payload.update(cloud_enabled=False, clear_cloud_key=True)
    r = c.put("/v2/models/config", json=payload)
    assert r.status_code == 200 and not r.json()["cloud_key_configured"]
    assert not list(directory.glob("*.json"))


def test_no_cloud_egress_after_memory_correction(factory):
    holder = {}
    seen = []

    def handler(req):
        seen.append(req)
        correction(holder["c"], holder["memory"])
        return local("需要帮助", "needs_cloud", "capability_limit")

    app, c = factory(handler)
    holder["c"] = c
    holder["memory"] = saved_memory(c)
    enable(c)
    r = post(c, "turns", {"text": "我喜欢喝茶吗"}).json()
    assert len(seen) == 1 and r["error"] == "context_snapshot_invalidated"


def test_recovery_marks_expired_dispatch_unknown_without_retry(factory):
    from datetime import datetime, timezone, timedelta

    app, c = factory()
    svc = app.state.service
    turn = svc.start_turn("崩溃前请求", "crashed")
    _, snapshot = svc.model_context("崩溃前请求")
    conf = app.state.model_settings.runtime()
    id = app.state.router.reserve(turn["id"], "local", conf, snapshot, "primary")
    with app.state.db.tx() as s:
        row = s.get(Record, id)
        d = json.loads(row.payload)
        d["deadline_at"] = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        ).isoformat()
        row.payload = json.dumps(d)
    restarted = create_app(str(app.state.db.engine.url), token="test")
    assert restarted.state.service.list("model_invocation")[0]["status"] == "unknown"
    replay = svc.start_turn("崩溃前请求", "crashed")
    current = next(t for t in svc.list("turn") if t["id"] == turn["id"])
    assert (
        current["status"] == "failed"
        and current["error"] == "inference_outcome_unknown"
    )
    assert len(svc.list("model_invocation")) == 1


def test_model_memory_write_claim_is_grounded_in_actual_receipt(factory):
    app, c = factory(
        lambda req: local(
            "好的，我记住了：我喜欢喝茶。还有其他问题吗？",
            memories=[{"quote": "我喜欢喝茶"}],
        )
    )
    result = post(c, "turns", {"text": "我喜欢喝茶"}).json()
    assert "我记住了" not in result["reply"] and "待审阅" in result["reply"]
    assert result["memory_receipt"] == {
        "status": "pending_review",
        "long_term_memory_written": False,
    }
    assert not c.get("/v2/memories").json()


def test_delete_historical_source_keeps_independent_current_correction(factory):
    app, c = factory()
    old = saved_memory(c)
    new = correction(c, old).json()
    assert (
        c.delete("/v2/records/" + old["source_ids"][0] + "?revision=1").status_code
        == 200
    )
    assert c.get("/v2/memories").json()[0]["text"] == new["text"]
    assert c.get("/v2/memories", params={"q": "咖啡"}).json()["results"]


def test_personal_recall_uses_only_confirmed_facts_not_poisoned_dialogue(factory):
    seen = []

    def handler(req):
        seen.append(json.loads(req.content))
        return local("你喜欢喝茉莉花茶。")

    app, c = factory(handler)
    memory = saved_memory(c, "我现在喜欢喝温水。")
    old = app.state.service.start_turn("随便聊聊", "poison")
    app.state.service.finish_turn(old["id"], text="你喜欢喝茉莉花茶。")
    result = post(c, "turns", {"text": "我喜欢喝什么？"}).json()
    assert "温水" in result["reply"] and "茉莉花茶" not in result["reply"]
    assert result["model_route"]["used_memory_ids"] == [memory["id"]]
    assert result["model_route"]["question_subject"] == "owner"
    context = json.loads(seen[0]["messages"][1]["content"].split("：", 1)[1])
    assert all(e["kind"] == "quoted_memory" for e in context)
    assert context[0]["subject"] == "owner" and context[0]["speaker"] == "owner"
    assert context[0]["statement"] == "用户现在喜欢喝温水。"
    assert context[0]["quote"] == "我现在喜欢喝温水。"
    assert "我喜欢喝" not in result["reply"]


def test_forgotten_personal_question_is_owner_unknown_even_if_model_invents(factory):
    seen = []

    def handler(req):
        seen.append(req)
        return local(
            "用户询问我喜欢喝什么，我喜欢喝茉莉花茶。", "needs_cloud", "knowledge_gap"
        )

    app, c = factory(handler)
    m = saved_memory(c, "我现在喜欢喝温水。")
    enable(c)
    c.delete("/v2/memories/" + m["id"] + "?revision=1")
    result = post(
        c, "turns", {"text": "我喜欢喝什么？如果没有我的记录，请直接说明不知道。"}
    ).json()
    assert result["model_route"]["question_subject"] == "owner"
    assert result["model_route"]["answer_basis"] == "no_confirmed_memory"
    assert result["model_route"]["used_memory_ids"] == []
    assert "不知道你喜欢喝什么" in result["reply"]
    assert all(
        term not in result["reply"]
        for term in ("温水", "茉莉花茶", "用户询问我", "我喜欢喝")
    )
    assert len(seen) == 1


def test_assistant_question_does_not_use_owner_preferences(factory):
    seen = []

    def handler(req):
        seen.append(json.loads(req.content))
        return local("我喜欢喝温水。")

    app, c = factory(handler)
    saved_memory(c, "我现在喜欢喝温水。")
    result = post(c, "turns", {"text": "你喜欢喝什么？"}).json()
    assert result["model_route"]["question_subject"] == "assistant"
    assert result["model_route"]["answer_basis"] == "assistant_identity"
    assert "温水" not in result["reply"] and "没有真实的饮品偏好" in result["reply"]
    assert "温水" not in seen[0]["messages"][1]["content"]


def test_reviewed_subject_and_subject_correction_are_preserved(factory):
    app, c = factory()
    source = material(c, "我喜欢喝温水。")
    p = post(
        c, "memory/proposals", {"text": "我喜欢喝温水。", "source_id": source["id"]}
    ).json()
    r = post(
        c,
        "memory/proposals/" + p["id"] + "/review",
        {"revision": p["revision"], "decision": "approve", "subject": "other"},
        "review-other",
    ).json()
    m = c.get("/v2/memories").json()[0]
    assert m["subject"] == "other"
    result = post(c, "turns", {"text": "我喜欢喝什么？"}, "question").json()
    assert result["model_route"]["answer_basis"] == "no_confirmed_memory"
    fixed = c.patch(
        "/v2/memories/" + m["id"],
        json={
            "revision": m["revision"],
            "text": m["text"],
            "reason": "明确指的是用户本人",
            "subject": "owner",
        },
        headers={"Idempotency-Key": "subject-correct"},
    ).json()
    assert fixed["subject"] == "owner"
    assert [
        v["subject"] for v in c.get("/v2/memories/" + m["id"] + "/history").json()
    ] == ["other", "owner"]


def test_explicit_memory_statement_ack_has_correct_subject(factory):
    app, c = factory(
        lambda req: local(
            "我喜欢喝茉莉花茶。", memories=[{"quote": "我喜欢喝茉莉花茶。"}]
        )
    )
    result = post(c, "turns", {"text": "请记住，我喜欢喝茉莉花茶。"}).json()
    assert "关于你的待审阅" in result["reply"]
    assert "我喜欢" not in result["reply"] and "我记住了" not in result["reply"]
    assert result["memory_receipt"]["long_term_memory_written"] is False
