import base64
import json
import pytest
from fastapi.testclient import TestClient
from fairy.app import create_app
from fairy.learning import LearningService
from fairy.knowledge import KnowledgeService
from fairy.worker import tick
from tests.db import postgres_url


@pytest.fixture
def env(tmp_path):
    app = create_app(postgres_url(tmp_path), token="t")
    c = TestClient(app)
    c.headers["Authorization"] = "Bearer t"
    return app, c, KnowledgeService(app.state.db)


def upload(c, raw, key="file"):
    return c.post(
        "/v2/learning/files",
        json={"filename": "a.txt", "content_base64": base64.b64encode(raw).decode()},
        headers={"Idempotency-Key": key},
    )


def test_file_idempotency_uses_original_bytes(env):
    app, c, svc = env
    assert upload(c, b"facts").status_code == 200
    assert upload(c, b"\xef\xbb\xbffacts").status_code == 409


def prepared(env):
    app, c, svc = env
    r = upload(c, "植物需要水分。".encode()).json()
    tick(app.state.db)
    course = svc.list("course")[0]
    return app, c, svc, course, r["material"]


def test_latest_review_order_not_practice_creation_order(env):
    app, c, svc, course, _ = prepared(env)
    a = svc.practice(course["id"], course["revision"], "第一份", "植物需要水分。", "p1")
    b = svc.practice(course["id"], course["revision"], "第二份", "植物需要水分。", "p2")
    svc.grade(b["id"], 1, 1, "仍需练习")
    svc.grade(a["id"], 1, 5, "最后复核通过")
    assert (
        c.post(
            "/v2/learning/courses/" + course["id"] + "/assess",
            json={
                "revision": course["revision"],
                "passed": True,
                "evidence": "植物需要水分。",
            },
        ).status_code
        == 200
    )


def test_regrading_failure_revokes_mastery_and_acquired_knowledge(env):
    app, c, svc, course, _ = prepared(env)
    a = svc.practice(course["id"], course["revision"], "答案", "植物需要水分。", "p1")
    graded = svc.grade(a["id"], 1, 5, "通过")
    app.state.service.assess(course["id"], course["revision"], True, "植物需要水分。")
    app.state.service.acquire(course["id"], "skill")
    svc.grade(a["id"], graded["revision"], 0, "发现关键错误")
    assert not svc.list("course")[0]["mastered"]
    assert not c.get("/v2/skills").json()


def test_disputed_source_cannot_be_acquired(env):
    app, c, svc, course, source = prepared(env)
    a = svc.practice(course["id"], course["revision"], "答案", "植物需要水分。", "p1")
    svc.grade(a["id"], 1, 5, "通过")
    app.state.service.assess(course["id"], course["revision"], True, "植物需要水分。")
    svc.source_review(source["id"], source["revision"], "disputed", "发现争议", None)
    with pytest.raises(Exception):
        app.state.service.acquire(course["id"], "unsafe")


def test_malformed_source_expiry_fails_closed(env):
    app, c, svc, course, source = prepared(env)
    with app.state.db.tx() as session:
        material = svc.get(session, source["id"], "material")
        payload = json.loads(material.payload)
        payload["quality"] = {
            "rating": "primary",
            "reason": "测试损坏的到期字段",
            "expires_at": "not-a-timestamp",
        }
        material.payload = json.dumps(payload)
        assert svc.source_eligible(material) is False
    listed = c.get("/v2/learning/sources").json()
    assert listed[0]["source_eligible"] is False


def test_final_course_confirmation_requires_exact_source_evidence(env):
    app, c, svc, course, _ = prepared(env)
    practice = svc.practice(
        course["id"],
        course["revision"],
        "植物需要水分。",
        "植物需要水分。",
        "practice",
    )
    svc.grade(practice["id"], 1, 4, "通过")
    path = "/v2/learning/courses/" + course["id"] + "/assess"
    assert (
        c.post(
            path,
            json={
                "revision": course["revision"],
                "passed": True,
                "evidence": "我认真看过了",
            },
        ).status_code
        == 422
    )
    assert (
        c.post(
            path,
            json={
                "revision": course["revision"],
                "passed": True,
                "evidence": "植物需要水分。",
            },
        ).status_code
        == 200
    )


def test_source_dispute_after_acquisition_revokes_skill_and_is_audited(env):
    app, c, svc, course, source = prepared(env)
    practice = svc.practice(
        course["id"],
        course["revision"],
        "植物需要水分。",
        "植物需要水分。",
        "practice",
    )
    svc.grade(practice["id"], 1, 4, "通过")
    app.state.service.assess(course["id"], course["revision"], True, "植物需要水分。")
    skill = app.state.service.acquire(course["id"], "skill")
    svc.source_review(
        source["id"], source["revision"], "disputed", "来源发生争议", None
    )
    assert not c.get("/v2/skills").json()
    revoked = [
        event
        for event in c.get("/v2/events").json()
        if event["type"] == "learning.mastery_revoked"
    ]
    assert revoked[-1]["payload"]["acquired_skill_ids"] == [skill["id"]]
    effect = c.get("/v2/learning/courses/" + course["id"] + "/effect").json()
    assert effect["source_eligible"] is False
    assert effect["latest_score"] is None
    assert effect["historical_latest_score"] == 4


def test_cancelling_assessment_marks_started_invocation_unknown(env):
    app, c, svc = env
    with app.state.db.tx() as session:
        attempt = app.state.db.add(
            session,
            "owner",
            "assessment_attempt",
            {"source_ids": [], "mode": "closed_book"},
            "pending",
        )
    conf = app.state.model_settings.runtime()
    invocation_id = app.state.router.reserve(
        attempt.id, "local", conf, {}, "owner_requested_assessment"
    )
    result = c.post("/v2/learning/assessment-runs/" + attempt.id + "/cancel").json()
    assert result["status"] == "interrupted"
    invocation = next(
        row
        for row in c.get("/v2/models/invocations").json()
        if row["id"] == invocation_id
    )
    assert invocation["status"] == "unknown"
    assert invocation["error"] == "request_cancelled"


def test_world_claim_can_be_withdrawn_without_deleting_source(env):
    app, c, svc, course, source = prepared(env)
    claim = svc.claim("植物", "需求", "水分", source["id"], "植物需要水分。", "claim")
    with app.state.db.tx() as session:
        app.state.db.add(
            session,
            "owner",
            "turn",
            {
                "text": "植物需要什么？",
                "reply": "水分。",
                "source_ids": [claim["id"]],
                "generation": 1,
            },
            "completed",
        )
    assert c.delete("/v2/records/" + claim["id"] + "?revision=1").status_code == 200
    assert c.get("/v2/world/claims").json() == []
    assert svc.list("turn") == []


def test_ineligible_source_is_visible_but_disabled_across_learning_apis(env):
    app, c, svc, course, source = prepared(env)
    quiz = c.post(
        "/v2/learning/quizzes",
        json={
            "source_id": source["id"],
            "title": "来源状态测验",
            "evidence": "植物需要水分。",
            "questions": [
                {
                    "question": "植物需要什么？",
                    "choices": ["水分", "火焰"],
                    "correct_index": 0,
                }
            ],
        },
        headers={"Idempotency-Key": "eligibility-quiz"},
    )
    assert quiz.status_code == 200
    svc.source_review(
        source["id"],
        source["revision"],
        "rejected",
        "来源不采纳",
        None,
    )
    assert c.get("/v2/learning/sources").json()[0]["source_eligible"] is False
    assert c.get("/v2/learning/courses").json()[0]["source_eligible"] is False
    assert c.get("/v2/learning/quizzes").json()[0]["source_eligible"] is False
