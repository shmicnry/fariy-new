"""Pet mood derives from persisted signals; appearance config is validated and survives full PUT."""

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


def pet_state(client):
    response = client.get("/v2/pet/state")
    assert response.status_code == 200, response.text
    return response.json()


def accept_topic_goal(client):
    created = client.post("/v2/autonomy/refresh", json={})
    assert created.status_code == 200, created.text
    candidate = [
        item for item in created.json() if item["type"] == "topic"
    ][0]
    accepted = client.post(
        f"/v2/autonomy/candidates/{candidate['id']}/accept",
        json={"revision": candidate["revision"]},
    )
    assert accepted.status_code == 200, accepted.text
    return accepted.json()["goal"]


def test_appearance_config_validation(env):
    _, client = env
    for overrides in (
        {"pet_skin": "catgirl"},
        {"pet_skin": "live2d"},
        {"pet_skin": "vrm", "pet_model_url": "http://example.com/model.vrm"},
        {"pet_model_url": "https://example.com/\x00model.json"},
    ):
        configs = client.get("/v2/config").json()
        payload = {"revision": configs[0]["revision"] if configs else 0}
        payload.update(overrides)
        response = client.put("/v2/config", json=payload)
        assert response.status_code == 422, (overrides, response.text)


def test_default_state_is_calm_with_builtin_appearance(env):
    _, client = env
    state = pet_state(client)
    assert state["mood"] == "calm"
    assert state["label"] == "平静待机"
    assert state["reasons"]
    assert state["signals"]["pending_approvals"] == 0
    assert state["signals"]["active_goals"] == 0
    assert state["appearance"] == {
        "skin": "builtin",
        "model_url": "",
        "fallback": "builtin",
    }


def test_pending_approval_drives_waiting_then_resolves(env):
    _, client = env
    proposed = client.post(
        "/v2/approvals",
        json={"title": "保存笔记", "text": "用户喜欢温水。"},
        headers={"Idempotency-Key": "pet-approval-1"},
    )
    assert proposed.status_code == 200, proposed.text
    approval = proposed.json()

    state = pet_state(client)
    assert state["mood"] == "waiting"
    assert state["signals"]["pending_approvals"] == 1
    assert "确认" in state["reasons"][0]

    rejected = client.post(
        f"/v2/approvals/{approval['id']}/choices",
        json={
            "revision": approval["revision"],
            "action_digest": approval["digest"],
            "choice": "reject",
        },
        headers={"Idempotency-Key": "pet-approval-1-reject"},
    )
    assert rejected.status_code == 200, rejected.text
    state = pet_state(client)
    assert state["mood"] == "calm"
    assert state["signals"]["pending_approvals"] == 0


def test_goal_lifecycle_drives_busy_then_fulfilled(env):
    _, client = env
    configure(client)
    goal = accept_topic_goal(client)
    assert goal["status"] == "planned"
    assert pet_state(client)["mood"] == "calm"

    started = client.post(
        f"/v2/autonomy/goals/{goal['id']}/start",
        json={"revision": goal["revision"]},
    )
    assert started.status_code == 200, started.text
    state = pet_state(client)
    assert state["mood"] == "busy"
    assert state["signals"]["active_goals"] == 1

    completed = client.post(
        f"/v2/autonomy/goals/{goal['id']}/complete",
        json={"revision": started.json()["revision"], "summary": "已整理海洋酸化要点。"},
    )
    assert completed.status_code == 200, completed.text
    state = pet_state(client)
    assert state["mood"] == "fulfilled"
    assert state["signals"]["completed_today"] == 1
    assert state["signals"]["active_goals"] == 0


def test_exhausted_budget_drives_resting(env):
    _, client = env
    configure(client, autonomy_daily_minutes=20)
    accept_topic_goal(client)
    state = pet_state(client)
    assert state["signals"]["remaining_minutes"] == 0
    assert state["mood"] == "resting"
    assert "预算" in state["reasons"][0]


def test_full_config_put_preserves_topics_and_appearance(env):
    _, client = env
    configure(
        client,
        pet_enabled=True,
        pet_skin="live2d",
        pet_model_url="https://example.com/fairy.model3.json",
    )
    stored = client.get("/v2/config").json()[0]
    # Mirror the iOS client: decode the stored config, flip one flag, PUT it back whole.
    payload = {key: value for key, value in stored.items() if key not in ("id", "scope", "kind", "status", "created_at")}
    payload["pet_enabled"] = False
    response = client.put("/v2/config", json=payload)
    assert response.status_code == 200, response.text
    after = client.get("/v2/config").json()[0]
    assert after["pet_enabled"] is False
    assert after["autonomy_topics"] == ["海洋酸化"]
    assert after["autonomy_topic_enabled"] is True
    assert after["pet_skin"] == "live2d"
    assert after["pet_model_url"] == "https://example.com/fairy.model3.json"
    state = pet_state(client)
    assert state["appearance"]["skin"] == "live2d"
    assert state["appearance"]["model_url"] == "https://example.com/fairy.model3.json"
