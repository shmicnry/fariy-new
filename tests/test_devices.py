"""设备配对与吊销：令牌只出现一次、哈希存储、设备权限边界、SSE 吊销切断。"""

import asyncio
import json

from fairy.store import Record, Request
from tests.test_p1 import factory, post  # noqa: F401


def test_pair_token_shown_once_and_replay(factory):
    app, c = factory()
    r = post(c, "devices", {"name": "办公室 iPhone"}, key="pair-1")
    assert r.status_code == 200
    data = r.json()
    assert data["token"].startswith("fd_")
    assert "token_hash" not in data

    replay = post(c, "devices", {"name": "办公室 iPhone"}, key="pair-1").json()
    assert replay["id"] == data["id"]
    assert replay["token"] is None

    listing = c.get("/v2/devices").json()
    assert len(listing) == 1
    assert listing[0]["name"] == "办公室 iPhone"
    assert "token_hash" not in listing[0]
    assert "token" not in listing[0]

    # 数据库与幂等缓存都只保存哈希，明文令牌不落盘。
    with app.state.db.sessions() as s:
        device_row = s.query(Record).filter(Record.kind == "device").one()
        assert data["token"] not in device_row.payload
        assert "token_hash" in json.loads(device_row.payload)
        for req in s.query(Request).all():
            assert data["token"] not in req.result


def test_pair_name_validation(factory):
    app, c = factory()
    assert post(c, "devices", {"name": "   "}, key="n1").status_code == 422
    assert post(c, "devices", {"name": ""}, key="n2").status_code == 422
    assert post(c, "devices", {"name": "长" * 65}, key="n3").status_code == 422
    assert c.get("/v2/devices").json() == []


def test_device_token_scope_and_revocation(factory):
    app, c = factory()
    d = post(c, "devices", {"name": "iPad"}, key="pair-2").json()
    h = {"Authorization": "Bearer " + d["token"]}

    # 设备令牌可以读事件，但不能配对或吊销（需要主令牌）。
    assert c.get("/v2/events", headers=h).status_code == 200
    r = c.post(
        "/v2/devices",
        json={"name": "别的设备"},
        headers={**h, "Idempotency-Key": "pair-by-device"},
    )
    assert r.status_code == 403
    assert r.json()["detail"] == "master_token_required"
    r = c.post(f"/v2/devices/{d['id']}/revoke", headers=h)
    assert r.status_code == 403

    # 吊销幂等：第二次不再增加 revision。
    r1 = c.post(f"/v2/devices/{d['id']}/revoke").json()
    assert r1["status"] == "revoked"
    r2 = c.post(f"/v2/devices/{d['id']}/revoke").json()
    assert r2["revision"] == r1["revision"]

    assert c.get("/v2/events", headers=h).status_code == 401
    assert (
        c.get(
            "/v2/events", headers={"Authorization": "Bearer fd_not_a_real_token"}
        ).status_code
        == 401
    )
    # 主令牌不受影响。
    assert c.get("/v2/events").status_code == 200


def test_stream_cuts_off_revoked_device(factory):
    app, c = factory()
    d = post(c, "devices", {"name": "测试手机"}, key="pair-stream").json()
    token = d["token"]

    async def scenario():
        # 直接驱动 ASGI 应用：httpx.ASGITransport 会缓冲整个响应，
        # 无法用于永不结束的 SSE 流，所以这里手工收集 send 消息。
        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/v2/stream",
            "raw_path": b"/v2/stream",
            "query_string": b"",
            "root_path": "",
            "headers": [
                (b"host", b"testserver"),
                (b"authorization", f"Bearer {token}".encode()),
            ],
            "client": ("127.0.0.1", 40000),
            "server": ("testserver", 80),
        }
        messages = []
        first_body = asyncio.Event()

        async def receive():
            await asyncio.sleep(3600)
            return {"type": "http.disconnect"}

        async def send(message):
            messages.append(message)
            if message["type"] == "http.response.body":
                first_body.set()

        task = asyncio.create_task(app(scope, receive, send))
        try:
            await asyncio.wait_for(first_body.wait(), 10)
            # 收到首帧后吊销设备，流必须在下一轮检查时自行结束。
            app.state.devices.revoke(d["id"])
            await asyncio.wait_for(task, 10)
        finally:
            task.cancel()

        start = next(m for m in messages if m["type"] == "http.response.start")
        assert start["status"] == 200
        body = b"".join(
            m.get("body", b"")
            for m in messages
            if m["type"] == "http.response.body"
        )
        assert b"event: device.revoked" in body

    asyncio.run(scenario())
    # 流结束后设备令牌立即失效。
    assert (
        c.get("/v2/events", headers={"Authorization": "Bearer " + token}).status_code
        == 401
    )
