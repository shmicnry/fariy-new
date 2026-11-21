"""Owner-registered autonomy topics: gated proposal, budget, lifecycle, validation."""

import pytest
from fastapi.testclient import TestClient

from fairy.app import create_app
from tests.db import postgres_url


@pytest.fixture
def env(tmp_path):
    app = create_app(postgres_url(tmp_path), token="owner")
    client = TestClient(app)
    client.headers["Authorization"] = "Bearer owner"
    return app, client


def configure(client, **overrides):
    payload = {
        "autonomy_enabled": True,
        "autonomy_daily_minutes": 30,
        "autonomy_daily_items": 10,
        "autonomy_topic_enabled": True,
        "autonomy_topics": ["海洋酸化"],
        "source_allowed_hosts": ["*.example.com"],
    }
    payload.update(overrides)
    configs = client.get("/v2/config").json()
    payload["revision"] = configs[0]["revision"] if configs else 0
    response = client.put("/v2/config", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def refresh(client):
    response = client.post("/v2/autonomy/refresh", json={})
    assert response.status_code == 200, response.text
    return response.json()


def topic_candidates(client):
    return [
        item
        for item in client.get("/v2/autonomy/candidates").json()
        if item["type"] == "topic"
    ]


def test_topics_require_flag_and_allowlist(env):
    _, client = env
    configure(client, autonomy_topic_enabled=False)
    refresh(client)
    assert topic_candidates(client) == []

    configure(client, source_allowed_hosts=[])
    refresh(client)
    assert topic_candidates(client) == []

    configure(client)
    created = refresh(client)
    assert len(created) == 1
    candidate = created[0]
    assert candidate["type"] == "topic"
    assert candidate["origin"] == "owner_topic"
    assert candidate["status"] == "proposed"
    assert candidate["estimated_minutes"] == 20
    assert candidate["allowed_hosts"] == ["*.example.com"]
    assert "海洋酸化" in candidate["title"]
    assert "允许域名" in candidate["success_condition"]

    again = refresh(client)
    assert [item for item in again if item["type"] == "topic"] == []
    assert len(topic_candidates(client)) == 1


def test_topic_accept_disabled_budget_and_goal_payload(env):
    _, client = env
    configure(
        client,
        autonomy_enabled=False,
        autonomy_daily_items=1,
        autonomy_topics=["海洋酸化", "珊瑚礁"],
    )
    refresh(client)
    candidates = topic_candidates(client)
    assert len(candidates) == 2

    denied = client.post(
        f"/v2/autonomy/candidates/{candidates[0]['id']}/accept",
        json={"revision": candidates[0]["revision"]},
    )
    assert denied.status_code == 409
    assert denied.json()["detail"] == "autonomy_disabled"

    configure(client, autonomy_daily_items=1, autonomy_topics=["海洋酸化", "珊瑚礁"])
    accepted = client.post(
        f"/v2/autonomy/candidates/{candidates[0]['id']}/accept",
        json={"revision": candidates[0]["revision"]},
    )
    assert accepted.status_code == 200, accepted.text
    body = accepted.json()
    goal = body["goal"]
    assert goal["status"] == "planned"
    assert goal["reserved_minutes"] == 20
    assert goal["allowed_hosts"] == ["*.example.com"]
    assert "允许域名" in goal["success_condition"]
    assert body["budget"]["remaining_minutes"] == 10
    assert body["budget"]["remaining_items"] == 0

    exhausted = client.post(
        f"/v2/autonomy/candidates/{candidates[1]['id']}/accept",
        json={"revision": candidates[1]["revision"]},
    )
    assert exhausted.status_code == 409
    assert exhausted.json()["detail"] == "autonomy_budget_exhausted"


def test_topic_accept_requires_enough_minutes(env):
    _, client = env
    configure(client, autonomy_daily_minutes=10)
    refresh(client)
    candidate = topic_candidates(client)[0]
    response = client.post(
        f"/v2/autonomy/candidates/{candidate['id']}/accept",
        json={"revision": candidate["revision"]},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "autonomy_budget_exhausted"


def test_dismissed_topic_stays_dismissed_until_text_changes(env):
    """「暂不处理」持久忽略同一主题文本；改写文本才会产生新候选。"""
    _, client = env
    configure(client)
    refresh(client)
    candidate = topic_candidates(client)[0]
    dismissed = client.post(
        f"/v2/autonomy/candidates/{candidate['id']}/dismiss",
        json={"revision": candidate["revision"]},
    )
    assert dismissed.status_code == 200
    assert dismissed.json()["status"] == "dismissed"

    created = refresh(client)
    assert [item for item in created if item["type"] == "topic"] == []
    topics = topic_candidates(client)
    assert len(topics) == 1
    assert topics[0]["status"] == "dismissed"

    configure(client, autonomy_topics=["海洋酸化", "珊瑚礁白化"])
    created = refresh(client)
    fresh = [item for item in created if item["type"] == "topic"]
    assert len(fresh) == 1
    assert "珊瑚礁白化" in fresh[0]["title"]
    assert fresh[0]["status"] == "proposed"


def test_topic_goal_lifecycle_settles_budget(env):
    _, client = env
    configure(client)
    refresh(client)
    candidate = topic_candidates(client)[0]
    goal = client.post(
        f"/v2/autonomy/candidates/{candidate['id']}/accept",
        json={"revision": candidate["revision"]},
    ).json()["goal"]

    started = client.post(
        f"/v2/autonomy/goals/{goal['id']}/start", json={"revision": goal["revision"]}
    )
    assert started.status_code == 200, started.text
    assert started.json()["status"] == "active"

    empty = client.post(
        f"/v2/autonomy/goals/{goal['id']}/complete",
        json={"revision": started.json()["revision"], "summary": "  "},
    )
    assert empty.status_code == 422

    completed = client.post(
        f"/v2/autonomy/goals/{goal['id']}/complete",
        json={
            "revision": started.json()["revision"],
            "summary": "已在允许域名内导入来源并完成练习",
        },
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "completed"
    assert completed.json()["verification"] == "owner_reported"
    budget = client.get("/v2/autonomy/budget").json()
    assert budget["remaining_minutes"] >= 29
    assert budget["remaining_items"] == 9


def test_topic_validation(env):
    _, client = env
    for topics in ([""], ["bad\x01topic"], ["x" * 121], [f"t{i}" for i in range(21)]):
        response = client.put(
            "/v2/config", json={"revision": 0, "autonomy_topics": topics}
        )
        assert response.status_code == 422, topics

    saved = configure(client, autonomy_topics=["  海洋酸化  ", "海洋酸化"])
    assert saved["autonomy_topics"] == ["海洋酸化"]
