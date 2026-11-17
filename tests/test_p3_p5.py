from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from datetime import datetime, timedelta, timezone
import asyncio
import json
import os
import plistlib
import subprocess
import sys

import httpx
import pytest
from fastapi.testclient import TestClient

from fairy.app import create_app
from fairy.cognition import character_cosine, relevance
from fairy.semantic import cosine
from fairy.worker import WorkerLock, tick, write_status


@pytest.fixture
def env(tmp_path):
    app = create_app("sqlite:///" + str(tmp_path / "milestones.db"), token="owner")
    client = TestClient(app)
    client.headers["Authorization"] = "Bearer owner"
    return app, client


def test_builtin_skill_install_grant_invoke_and_disable(env):
    app, client = env
    registry = client.get("/v2/skills/registry").json()
    assert len(registry) == 6
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
    assert invocation.json()["invocation"]["status"] == "completed"
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


def test_config_allowlists_are_bounded_and_normalized(env):
    app, client = env
    base = {"revision": 0}
    assert (
        client.put(
            "/v2/config",
            json={**base, "mac_allowed_paths": ["relative/path"]},
        ).status_code
        == 422
    )
    assert (
        client.put(
            "/v2/config",
            json={**base, "mac_allowed_apps": ["TextEdit\n--help"]},
        ).status_code
        == 422
    )
    configured = client.put(
        "/v2/config",
        json={
            **base,
            "mac_allowed_apps": [" TextEdit ", "TextEdit"],
            "mac_allowed_paths": ["/tmp", "/tmp"],
        },
    )
    assert configured.status_code == 200, configured.text
    assert configured.json()["mac_allowed_apps"] == ["TextEdit"]
    assert configured.json()["mac_allowed_paths"] == ["/tmp"]


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


def test_mac_ax_tree_requires_helper_and_tcc(env):
    app, client = env
    registry = client.get("/v2/skills/registry").json()
    skill = next(item for item in registry if item["implementation"] == "mac_ax_tree")
    installed = client.post("/v2/skills/registry/" + skill["id"] + "/install").json()
    granted = client.post(
        "/v2/skills/registry/" + skill["id"] + "/grant",
        json={
            "revision": installed["revision"],
            "permissions": ["mac.read_ax"],
            "expires_minutes": 5,
        },
    )
    assert granted.status_code == 200
    result = client.post(
        "/v2/skills/registry/" + skill["id"] + "/invoke",
        json={"query": "com.apple.TextEdit"},
    )
    helper = client.get("/v2/mac/status").json().get("helper_version")
    assert result.status_code == (403 if helper else 503)


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


def test_local_character_vector_retrieval_handles_reordered_cjk():
    assert relevance("水温", "我喜欢喝温水") >= 0.25
    assert relevance("咖啡", "我喜欢喝温水") == 0
    assert character_cosine("温水", "温水") > 0.99
    assert character_cosine("咖啡", "水量") < 0.2


def test_semantic_embeddings_are_local_and_cached(tmp_path, monkeypatch):
    calls = []

    def handler(request):
        payload = json.loads(request.content)
        calls.append(payload)
        vectors = []
        for text in payload["input"]:
            vectors.append([1.0, 0.0] if "水" in text else [0.0, 1.0])
        return httpx.Response(200, json={"embeddings": vectors})

    monkeypatch.setenv("FAIRY_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("FAIRY_OLLAMA_MODEL", "")
    monkeypatch.setenv("FAIRY_EMBEDDING_MODEL", "test-embedding")
    app = create_app(
        "sqlite:///" + str(tmp_path / "semantic.db"),
        token="owner",
        transport=httpx.MockTransport(handler),
    )
    first = asyncio.run(app.state.semantic.embeddings(["水温", "咖啡"]))
    second = asyncio.run(app.state.semantic.embeddings(["水温", "咖啡"]))
    assert first == second == [[1.0, 0.0], [0.0, 1.0]]
    assert len(calls) == 1
    assert cosine(first[0], first[1]) == 0


def test_worker_status_endpoint_and_stale_lock_recovery(env, tmp_path):
    app, client = env
    state = tmp_path / "worker-state"
    state.mkdir()
    write_status(
        state,
        {
            "pid": os.getpid(),
            "started_at": datetime.now(timezone.utc).isoformat(),
            "heartbeat_at": datetime.now(timezone.utc).isoformat(),
            "cycle": 3,
            "status": "running",
            "error": None,
        },
    )
    app.state.worker_state_dir = str(state)
    status = client.get("/v2/worker/status")
    assert status.status_code == 200
    assert status.json()["alive"] is True
    assert status.json()["cycle"] == 3

    (state / "worker.pid").write_text("99999999", encoding="utf-8")
    with WorkerLock(state) as lock:
        assert lock.acquired is True
        assert (state / "worker.pid").read_text(encoding="utf-8") == str(os.getpid())
    assert not (state / "worker.pid").exists()


def test_macos_worker_service_dry_run_generates_valid_plist(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts" / "fairy_worker_service.sh"
    plist = tmp_path / "io.fairy.worker.plist"
    env = {
        **os.environ,
        "FAIRY_LAUNCHD_DRY_RUN": "1",
        "FAIRY_LAUNCHD_PLIST": str(plist),
        "FAIRY_PYTHON": sys.executable,
        "FAIRY_WORKER_RUNTIME": str(tmp_path / "runtime"),
        "FAIRY_STATE_DIR": str(tmp_path / "state"),
        "FAIRY_LOG_DIR": str(tmp_path / "logs"),
    }
    result = subprocess.run(
        ["sh", str(script), "install"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = plistlib.loads(plist.read_bytes())
    assert payload["Label"] == "io.fairy.worker"
    assert payload["RunAtLoad"] is True
    installed_python = str(tmp_path / "runtime" / ".venv" / "bin" / "python")
    assert payload["ProgramArguments"][:3] == [installed_python, "-m", "fairy.worker"]
    assert payload["EnvironmentVariables"]["FAIRY_STATE_DIR"] == str(tmp_path / "state")


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


def test_failed_skill_invocation_is_persisted_and_audited(env, monkeypatch):
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

    def denied(_bridge):
        from fairy.service import fail

        fail(503, "mac_status_failed")

    monkeypatch.setattr("fairy.skills.MacBridge.status", denied)
    result = client.post(
        "/v2/skills/registry/" + skill["id"] + "/invoke",
        json={"query": ""},
    )
    assert result.status_code == 503
    invocation = app.state.service.list("skill_invocation")[-1]
    assert invocation["status"] == "failed"
    assert invocation["error"] == "mac_status_failed"
    assert any(
        event["type"] == "skill.invocation_failed"
        and event["payload"]["invocation_id"] == invocation["id"]
        for event in client.get("/v2/events").json()
    )


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
    assert "response.ok" in worker.text
    assert "event.request.mode === 'navigate'" in worker.text
    assert "fairy-shell-v11" in worker.text


def test_local_voice_status_and_tts(env, monkeypatch):
    app, client = env
    monkeypatch.delenv("FAIRY_WHISPER_CLI", raising=False)
    monkeypatch.delenv("FAIRY_WHISPER_MODEL", raising=False)
    status = client.get("/v2/voice/status")
    assert status.status_code == 200
    payload = status.json()
    assert payload["audio_persisted"] is False
    assert payload["cloud_used"] is False
    if payload["local_tts"]:
        result = client.post("/v2/voice/speak", json={"text": "Fairy 本地语音测试"})
        assert result.status_code == 200
        assert result.headers["content-type"].startswith("audio/wav")
        assert result.content.startswith(b"RIFF")
    if not payload["local_asr"]:
        missing = client.post(
            "/v2/voice/transcribe",
            json={
                "audio_base64": "UklGRg==",
                "media_type": "audio/wav",
                "language": "zh",
            },
        )
        assert missing.status_code == 503
        assert missing.json()["detail"] == "local_asr_not_configured"


def test_lan_hosts_require_explicit_allowlist(env, monkeypatch):
    app, client = env
    assert client.get("/v2/capabilities", headers={"Host": "fairy.example"}).status_code == 421
    monkeypatch.setenv("FAIRY_ALLOW_LAN", "1")
    monkeypatch.setenv("FAIRY_ALLOWED_HOSTS", "fairy.example")
    assert client.get("/v2/capabilities", headers={"Host": "fairy.example"}).status_code == 200
    assert client.get("/v2/capabilities", headers={"Host": "other.example"}).status_code == 421
