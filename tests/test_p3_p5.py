from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from datetime import datetime, timedelta, timezone
import json

import pytest
from fastapi.testclient import TestClient

from fairy.app import create_app
from fairy.worker import tick


@pytest.fixture
def env(tmp_path):
    app = create_app("sqlite:///" + str(tmp_path / "milestones.db"), token="owner")
    client = TestClient(app)
    client.headers["Authorization"] = "Bearer owner"
    return app, client


def test_builtin_skill_install_grant_invoke_and_disable(env):
    app, client = env
    registry = client.get("/v2/skills/registry").json()
    assert len(registry) == 5
    status_skill = next(
        item for item in registry if item["implementation"] == "mac_status"
    )
    assert status_skill["installed"] is False
    assert (
        client.post(
            "/v2/skills/registry/" + status_skill["id"] + "/invoke",
            json={"query": ""},
        ).status_code
        == 409
    )
    installed = client.post(
        "/v2/skills/registry/" + status_skill["id"] + "/install"
    ).json()
    assert installed["installed"] is True and installed["enabled"] is False
    assert (
        client.post(
            "/v2/skills/registry/" + status_skill["id"] + "/grant",
            json={
                "revision": installed["revision"],
                "permissions": ["learning.read"],
                "expires_minutes": 10,
            },
        ).status_code
        == 422
    )
    granted = client.post(
        "/v2/skills/registry/" + status_skill["id"] + "/grant",
        json={
            "revision": installed["revision"],
            "permissions": ["mac.read_status"],
            "expires_minutes": 10,
        },
    )
    assert granted.status_code == 200, granted.text
    invocation = client.post(
        "/v2/skills/registry/" + status_skill["id"] + "/invoke",
        json={"query": ""},
    )
    assert invocation.status_code == 200
    assert invocation.json()["result"]["arbitrary_shell"] is False
    disabled = client.post(
        "/v2/skills/registry/" + status_skill["id"] + "/disable"
    ).json()
    assert disabled["enabled"] is False
    assert (
        client.post(
            "/v2/skills/registry/" + status_skill["id"] + "/invoke",
            json={"query": ""},
        ).status_code
        == 409
    )


def test_mac_files_realpath_confinement(env, tmp_path):
    app, client = env
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    (allowed / "visible.txt").write_text("safe")
    (outside / "secret.txt").write_text("secret")
    (allowed / "escape").symlink_to(outside, target_is_directory=True)
    assert (
        client.put(
            "/v2/config",
            json={"revision": 0, "mac_allowed_paths": [str(allowed)]},
        ).status_code
        == 200
    )
    listing = client.get("/v2/mac/files", params={"path": str(allowed)})
    assert listing.status_code == 200
    assert {item["name"] for item in listing.json()["entries"]} == {
        "visible.txt",
        "escape",
    }
    assert client.get("/v2/mac/files", params={"path": str(outside)}).status_code == 403
    assert (
        client.get(
            "/v2/mac/files", params={"path": str(allowed / "escape")}
        ).status_code
        == 403
    )
    assert client.get("/v2/mac/status").json()["execute_action_available"] is False
    assert client.get("/v2/mac/apps").json()["launch_available"] is False


def test_mac_open_app_requires_all_scopes_and_has_no_arbitrary_arguments(env):
    app, client = env
    registry = client.get("/v2/skills/registry").json()
    skill = next(item for item in registry if item["implementation"] == "mac_open_app")
    installed = client.post("/v2/skills/registry/" + skill["id"] + "/install").json()
    granted = client.post(
        "/v2/skills/registry/" + skill["id"] + "/grant",
        json={
            "revision": installed["revision"],
            "permissions": ["mac.open_app"],
            "expires_minutes": 5,
        },
    )
    assert granted.status_code == 200
    invocation_body = {"query": "TextEdit", "path": None}
    assert (
        client.post(
            "/v2/skills/registry/" + skill["id"] + "/invoke",
            json=invocation_body,
        ).status_code
        == 409
    )
    assert (
        client.put(
            "/v2/config",
            json={
                "revision": 0,
                "mac_execute": True,
                "mac_allowed_apps": ["TextEdit"],
            },
        ).status_code
        == 200
    )
    with patch(
        "fairy.mac_bridge.subprocess.run",
        return_value=SimpleNamespace(returncode=0, stdout="", stderr=""),
    ) as runner:
        result = client.post(
            "/v2/skills/registry/" + skill["id"] + "/invoke",
            json=invocation_body,
        )
    assert result.status_code == 200, result.text
    command = runner.call_args.args[0]
    assert command[:2] == ["/usr/bin/open", "-a"]
    assert command[2].endswith("TextEdit.app")
    assert result.json()["result"]["verification"].endswith("not_verified")


def test_autonomy_candidates_require_budget_and_create_goal(env):
    app, client = env
    material = app.state.service.material("课程", "植物需要水分。", "material")
    tick(app.state.db)
    course = app.state.service.list("course")[0]
    app.state.service.assess(course["id"], course["revision"], False, "需要继续练习")
    created = client.post("/v2/autonomy/refresh")
    assert created.status_code == 200
    candidate = next(item for item in created.json() if item["status"] == "proposed")
    assert (
        client.post(
            "/v2/autonomy/candidates/" + candidate["id"] + "/accept",
            json={"revision": candidate["revision"]},
        ).status_code
        == 409
    )
    payload = {
        "revision": 0,
        "autonomy_enabled": True,
        "autonomy_daily_minutes": 20,
        "autonomy_daily_items": 1,
    }
    assert client.put("/v2/config", json=payload).status_code == 200
    accepted = client.post(
        "/v2/autonomy/candidates/" + candidate["id"] + "/accept",
        json={"revision": candidate["revision"]},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["goal"]["status"] == "planned"
    budget = client.get("/v2/autonomy/budget").json()
    assert budget["used_items"] == 1 and budget["remaining_minutes"] == 5


def test_autonomy_item_limit_blocks_second_candidate(env):
    app, client = env
    courses = []
    for index in range(2):
        created = app.state.service.material(
            "课程" + str(index), "材料" + str(index), "material-" + str(index)
        )
        tick(app.state.db)
        course = next(
            item
            for item in app.state.service.list("course")
            if item["id"] == created["course"]["id"]
        )
        app.state.service.assess(
            course["id"], course["revision"], False, "继续练习"
        )
        courses.append(course)
    assert client.put(
        "/v2/config",
        json={
            "revision": 0,
            "autonomy_enabled": True,
            "autonomy_daily_minutes": 60,
            "autonomy_daily_items": 1,
        },
    ).status_code == 200
    candidates = client.post("/v2/autonomy/refresh").json()
    assert len(candidates) == 2
    assert client.post(
        "/v2/autonomy/candidates/" + candidates[0]["id"] + "/accept",
        json={"revision": candidates[0]["revision"]},
    ).status_code == 200
    assert client.post(
        "/v2/autonomy/candidates/" + candidates[1]["id"] + "/accept",
        json={"revision": candidates[1]["revision"]},
    ).status_code == 409


def test_single_refresh_deduplicates_world_conflicts(env):
    app, client = env
    service = app.state.service
    red = service.material("红色样本", "样品呈红色。", "red-material")["material"]
    blue = service.material("蓝色样本", "样品呈蓝色。", "blue-material")["material"]
    for source, value, quote, key in (
        (red, "红色", "样品呈红色。", "claim-red"),
        (blue, "蓝色", "样品呈蓝色。", "claim-blue"),
    ):
        response = client.post(
            "/v2/world/claims",
            json={
                "subject": "样品",
                "predicate": "颜色",
                "value": value,
                "source_id": source["id"],
                "quote": quote,
            },
            headers={"Idempotency-Key": key},
        )
        assert response.status_code == 200, response.text
    candidates = client.post("/v2/autonomy/refresh").json()
    conflicts = [
        item for item in candidates if item["type"] == "world_conflict"
    ]
    assert len(conflicts) == 1
    assert client.post("/v2/autonomy/refresh").json() == []


def test_expired_skill_grant_cannot_invoke(env):
    app, client = env
    registry = client.get("/v2/skills/registry").json()
    skill = next(
        item for item in registry if item["implementation"] == "mac_status"
    )
    installed = client.post(
        "/v2/skills/registry/" + skill["id"] + "/install"
    ).json()
    assert client.post(
        "/v2/skills/registry/" + skill["id"] + "/grant",
        json={
            "revision": installed["revision"],
            "permissions": ["mac.read_status"],
            "expires_minutes": 5,
        },
    ).status_code == 200
    with app.state.db.tx() as session:
        grant = app.state.service.rows(session, "skill_grant")[-1]
        payload = json.loads(grant.payload)
        payload["expires_at"] = (
            datetime.now(timezone.utc) - timedelta(minutes=1)
        ).isoformat()
        grant.payload = json.dumps(payload)
    assert client.post(
        "/v2/skills/registry/" + skill["id"] + "/invoke",
        json={"query": ""},
    ).status_code == 409


def test_isolated_evolution_lab_never_changes_runtime(env):
    app, client = env
    body = {
        "name": "回答约束实验",
        "baseline": "baseline",
        "cases": [
            {
                "input": "水的颜色",
                "required_terms": ["无色", "适用条件"],
                "forbidden_terms": ["保证"],
            },
            {
                "input": "未知信息",
                "required_terms": ["不确定"],
                "forbidden_terms": ["已确认"],
            },
        ],
        "candidates": [
            {
                "name": "baseline",
                "outputs": ["水通常无色。", "我不确定。"],
            },
            {
                "name": "candidate",
                "outputs": ["水通常无色，并注明适用条件。", "目前不确定。"],
            },
        ],
    }
    result = client.post(
        "/v2/evolution/experiments",
        json=body,
        headers={"Idempotency-Key": "experiment"},
    )
    assert result.status_code == 200, result.text
    experiment = result.json()
    assert experiment["runtime_changed"] is False
    assert experiment["scoring_immutable"] is True
    assert experiment["winner"] == "candidate"
    replay = client.post(
        "/v2/evolution/experiments",
        json=body,
        headers={"Idempotency-Key": "experiment"},
    ).json()
    assert replay["id"] == experiment["id"]
    approved = client.post(
        "/v2/evolution/experiments/" + experiment["id"] + "/approve",
        json={"candidate": "candidate"},
    )
    assert approved.json()["status"] == "approved_for_review"
    assert approved.json()["runtime_changed"] is False
    rolled_back = client.post(
        "/v2/evolution/experiments/" + experiment["id"] + "/rollback"
    )
    assert rolled_back.json()["status"] == "rolled_back"


def test_evolution_cannot_approve_non_improving_baseline(env):
    app, client = env
    body = {
        "name": "无提升实验",
        "baseline": "baseline",
        "cases": [
            {
                "input": "测试",
                "required_terms": ["正确"],
                "forbidden_terms": [],
            }
        ],
        "candidates": [
            {"name": "same", "outputs": ["正确"]},
            {"name": "baseline", "outputs": ["正确"]},
        ],
    }
    experiment = client.post(
        "/v2/evolution/experiments",
        json=body,
        headers={"Idempotency-Key": "no-improvement"},
    ).json()
    assert experiment["winner"] == "baseline"
    assert experiment["recommendation"] == "keep_baseline"
    assert (
        client.post(
            "/v2/evolution/experiments/" + experiment["id"] + "/approve",
            json={"candidate": "same"},
        ).status_code
        == 409
    )


def test_pwa_shell_is_served_and_does_not_cache_api(env):
    app, client = env
    manifest = client.get("/assets/manifest.webmanifest")
    assert manifest.status_code == 200
    assert manifest.json()["display"] == "standalone"
    assert client.get("/assets/apple-touch-icon.png").status_code == 200
    worker = client.get("/service-worker.js")
    assert worker.status_code == 200
    assert worker.headers["service-worker-allowed"] == "/"
    assert "url.pathname.startsWith('/v2/')" in worker.text
    assert "fairy-shell-v6" in worker.text


def test_lan_hosts_require_explicit_allowlist(env, monkeypatch):
    app, client = env
    assert client.get("/v2/capabilities", headers={"Host": "fairy.example"}).status_code == 421
    monkeypatch.setenv("FAIRY_ALLOW_LAN", "1")
    monkeypatch.setenv("FAIRY_ALLOWED_HOSTS", "fairy.example")
    assert client.get("/v2/capabilities", headers={"Host": "fairy.example"}).status_code == 200
    assert client.get("/v2/capabilities", headers={"Host": "other.example"}).status_code == 421
