"""第二轮审计修复的回归测试：计费、DNS 钉扎、文件排他、授权中途失效、同库恢复、状态文件防符号链接。"""

import asyncio
import json
import os
import socket
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from fairy.app import create_app
from fairy.maintenance import restore_database, run_backup, status_path, write_status
from fairy.models import ModelError, ModelRouter, pinned_request, public_cloud_address
from fairy.worker import tick
from tests.db import postgres_database, postgres_url
from tests.test_p1 import cloud, enable, factory, local, post  # noqa: F401
from tests.test_reliability_learning import upload


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("FAIRY_OLLAMA_MODEL", "fixture")
    app = create_app(postgres_url(tmp_path), token="owner")
    client = TestClient(app)
    client.headers["Authorization"] = "Bearer owner"
    return app, client


def test_cloud_missing_usage_keeps_reservation_and_flags_unknown(factory):
    calls = {"cloud": 0}

    def handler(req):
        if req.url.host == "127.0.0.1":
            return local("需要帮助", "needs_cloud", "capability_limit")
        calls["cloud"] += 1
        if calls["cloud"] == 1:
            return cloud()
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": "云端回答"}, "finish_reason": "stop"}
                ]
            },
        )

    app, c = factory(handler)
    enable(
        c,
        cloud_currency="USD",
        cloud_input_cents_per_million=100,
        cloud_output_cents_per_million=200,
    )
    assert post(c, "turns", {"text": "第一问"}, key="t1").json()["model_route"][
        "cloud_used"
    ]
    assert post(c, "turns", {"text": "第二问"}, key="t2").json()["model_route"][
        "cloud_used"
    ]
    rows = [
        row
        for row in c.get("/v2/models/invocations").json()
        if row["phase"] == "cloud"
    ]
    assert len(rows) == 2
    settled = next(row for row in rows if row["charge_status"] == "settled")
    unknown = next(row for row in rows if row["charge_status"] == "unknown")
    assert settled["cost_microcents"] == 5
    assert unknown["cost_microcents"] == unknown["reserved_microcents"] > 0
    budget = c.get("/v2/models/budget").json()
    assert budget["requests"] == 2
    assert budget["unknown_charges"] == 1
    assert budget["used_microcents"] == 5 + unknown["cost_microcents"]


def info(address):
    return (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))


def test_pinned_request_preserves_host_port_and_brackets_ipv6():
    pinned, headers, hostname = pinned_request(
        "https://provider.test/v1/chat", "203.0.113.7"
    )
    assert pinned == "https://203.0.113.7/v1/chat"
    assert headers == {"Host": "provider.test"}
    assert hostname == "provider.test"
    pinned, headers, _ = pinned_request(
        "https://provider.test:8443/v1", "2001:db8::1"
    )
    assert pinned == "https://[2001:db8::1]:8443/v1"
    assert headers == {"Host": "provider.test:8443"}


def test_public_cloud_address_rejects_private_mixed_and_garbage(monkeypatch):
    url = "https://provider.test/v1"
    monkeypatch.setattr(
        "fairy.models.socket.getaddrinfo", lambda *a, **k: [info("127.0.0.1")]
    )
    with pytest.raises(ModelError) as exc:
        public_cloud_address(url)
    assert exc.value.code == "cloud_destination_denied"
    monkeypatch.setattr(
        "fairy.models.socket.getaddrinfo",
        lambda *a, **k: [info("8.8.8.8"), info("10.0.0.5")],
    )
    with pytest.raises(ModelError) as exc:
        public_cloud_address(url)
    assert exc.value.code == "cloud_destination_denied"
    monkeypatch.setattr(
        "fairy.models.socket.getaddrinfo",
        lambda *a, **k: [info("8.8.4.4"), info("8.8.8.8")],
    )
    assert public_cloud_address(url) == "8.8.4.4"
    monkeypatch.setattr(
        "fairy.models.socket.getaddrinfo", lambda *a, **k: [info("not-an-ip")]
    )
    with pytest.raises(ModelError) as exc:
        public_cloud_address(url)
    assert exc.value.code == "cloud_destination_denied"

    def gaierror(*a, **k):
        raise socket.gaierror("no such host")

    monkeypatch.setattr("fairy.models.socket.getaddrinfo", gaierror)
    with pytest.raises(ModelError) as exc:
        public_cloud_address(url)
    assert exc.value.code == "cloud_unavailable"
    monkeypatch.setattr("fairy.models.socket.getaddrinfo", lambda *a, **k: [])
    with pytest.raises(ModelError) as exc:
        public_cloud_address(url)
    assert exc.value.code == "cloud_unavailable"


def test_mock_transport_never_resolves_and_real_router_pins_before_egress(
    factory, monkeypatch
):
    app, c = factory()

    def forbid(*a, **k):
        raise AssertionError("mock transport must not resolve DNS")

    monkeypatch.setattr("fairy.models.socket.getaddrinfo", forbid)
    router = ModelRouter(
        app.state.service,
        app.state.model_settings,
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json={})),
    )
    assert (
        asyncio.run(router._json("https://provider.test/v1/x", 5, pin_public=True))
        == {}
    )
    monkeypatch.setattr(
        "fairy.models.socket.getaddrinfo", lambda *a, **k: [info("192.168.1.9")]
    )
    real = ModelRouter(app.state.service, app.state.model_settings)
    with pytest.raises(ModelError) as exc:
        asyncio.run(real._json("https://provider.test/v1/x", 5, pin_public=True))
    assert exc.value.code == "cloud_destination_denied"


def install_and_grant(client, implementation, permissions):
    registry = client.get("/v2/skills/registry").json()
    skill = next(
        item for item in registry if item["implementation"] == implementation
    )
    installed = client.post(
        "/v2/skills/registry/" + skill["id"] + "/install"
    ).json()
    granted = client.post(
        "/v2/skills/registry/" + skill["id"] + "/grant",
        json={
            "revision": installed["revision"],
            "permissions": permissions,
            "expires_minutes": 5,
        },
    )
    assert granted.status_code == 200, granted.text
    return skill["id"]


def test_create_file_refuses_symlink_targets_including_dangling(env, tmp_path):
    app, client = env
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    victim = tmp_path / "victim.txt"
    victim.write_text("原始内容", encoding="utf-8")
    (allowed / "link.txt").symlink_to(victim)
    (allowed / "dangling.txt").symlink_to(tmp_path / "missing.txt")
    assert (
        client.put(
            "/v2/config",
            json={
                "revision": 0,
                "mac_file_write": True,
                "mac_allowed_paths": [str(allowed)],
            },
        ).status_code
        == 200
    )
    skill_id = install_and_grant(client, "mac_create_file", ["mac.write_file"])
    for name in ("link.txt", "dangling.txt"):
        response = client.post(
            "/v2/skills/registry/" + skill_id + "/invoke",
            json={"path": str(allowed / name), "content": "不应写入"},
        )
        assert response.status_code == 409, response.text
        assert response.json()["detail"] == "file_already_exists"
        assert (allowed / name).is_symlink()
    assert victim.read_text(encoding="utf-8") == "原始内容"
    assert not (tmp_path / "missing.txt").exists()


def test_grant_expiring_mid_invocation_withholds_result(env, monkeypatch):
    app, client = env
    assert upload(client).status_code == 200
    tick(app.state.db)
    skill_id = install_and_grant(client, "learning_search", ["learning.read"])
    monkeypatch.setattr(app.state.skills, "semantic", None, raising=False)
    from fairy import cognition

    original = cognition.relevance
    fired = []

    def expire_then_score(query, text):
        if not fired:
            fired.append(True)
            with app.state.db.tx() as session:
                grant = app.state.service.rows(session, "skill_grant")[-1]
                payload = json.loads(grant.payload)
                payload["expires_at"] = (
                    datetime.now(timezone.utc) - timedelta(minutes=1)
                ).isoformat()
                grant.payload = json.dumps(payload)
        return original(query, text)

    monkeypatch.setattr(cognition, "relevance", expire_then_score)
    response = client.post(
        "/v2/skills/registry/" + skill_id + "/invoke",
        json={"query": "第一段"},
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "skill_grant_expired"
    invocation = app.state.service.list("skill_invocation")[-1]
    assert invocation["status"] == "failed"
    assert invocation["error"] == "skill_grant_expired"
    assert "result" not in invocation
    assert any(
        event["type"] == "skill.invocation_failed"
        and event["payload"]["invocation_id"] == invocation["id"]
        and event["payload"]["error"] == "skill_grant_expired"
        for event in client.get("/v2/events").json()
    )


def test_restore_with_clean_succeeds_into_same_database(tmp_path):
    url = postgres_database()
    app = create_app(url, token="test")
    source = app.state.service.material("source", "我喜欢喝温水", "m")["material"]
    memory = app.state.service.memory("我喜欢喝温水", [source["id"]], "mem")
    app.state.service.correct(memory["id"], 1, "我喜欢喝茶", "修改", "edit")
    report = run_backup(url, tmp_path / "backups")
    app.state.db.engine.dispose()
    restored = restore_database(Path(report["file"]), url, report["sha256"])
    assert restored["restored"] is True
    service = create_app(url, token="test").state.service
    assert service.list("memory")[0]["text"] == "我喜欢喝茶"
    assert len(service.history(memory["id"])) == 2


def test_write_status_ignores_planted_symlink_temp(tmp_path):
    victim = tmp_path / "victim.json"
    victim.write_text("不可触碰", encoding="utf-8")
    temp = tmp_path / f"backup-status.json.{os.getpid()}.tmp"
    temp.symlink_to(victim)
    payload = {"status": "healthy", "healthy": True}
    write_status(tmp_path, payload)
    target = status_path(tmp_path)
    assert json.loads(target.read_text(encoding="utf-8")) == payload
    assert not target.is_symlink()
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert victim.read_text(encoding="utf-8") == "不可触碰"
    assert not temp.exists() and not temp.is_symlink()
