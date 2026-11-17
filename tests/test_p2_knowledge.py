import json
import socket
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from fairy.app import create_app
from fairy.knowledge import KnowledgeService
from fairy.link_fetch import validate_url, public_addresses, fetch_text, ArticleParser
from fairy.worker import tick


@pytest.fixture
def env(tmp_path):
    app = create_app("sqlite:///" + str(tmp_path / "test.db"), token="x")
    c = TestClient(app)
    c.headers["Authorization"] = "Bearer x"
    return app, c, KnowledgeService(app.state.db)


def test_link_import_is_reserved_and_not_refetched(env):
    app, c, svc = env
    calls = []
    r = svc.link(
        "https://example.com",
        "例子",
        "key",
        lambda url: (calls.append(url) or "植物需要水分。"),
    )
    same = svc.link(
        "https://example.com",
        "例子",
        "key",
        lambda _: pytest.fail("should not fetch twice"),
    )
    assert r["id"] == same["id"] and same["status"] == "completed" and len(calls) == 1
    material = svc.list("material")[0]
    assert (
        material["source_type"] == "web_link"
        and material["quality"]["rating"] == "unreviewed"
    )
    assert svc.list("course")[0]["practice_required"]


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "file:///etc/passwd",
        "https://user:pass@example.com",
        "https://example.com:8443",
    ],
)
def test_link_url_validation(url):
    with pytest.raises(ValueError):
        validate_url(url)


@pytest.mark.parametrize(
    "ip", ["127.0.0.1", "::1", "169.254.169.254", "10.0.0.1", "::ffff:127.0.0.1"]
)
def test_private_and_rebinding_addresses_denied(ip):
    with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", (ip, 443))]):
        with pytest.raises(ValueError):
            public_addresses("public-looking.example")


def test_html_does_not_execute_or_include_scripts():
    p = ArticleParser()
    p.feed("<h1>知识</h1><script>send_secret()</script><p>实际正文</p>")
    assert "send_secret" not in "".join(p.parts) and "实际正文" in "".join(p.parts)


def test_source_dispute_blocks_recall_and_world_conflicts(env):
    app, c, svc = env
    a = svc.material("a", "水的颜色是无色。", "a")["material"]
    b = svc.material("b", "水的颜色是蓝色。", "b")["material"]
    app.state.service.memory("水的颜色是无色。", [a["id"]], "memory")
    first = svc.claim("水", "颜色", "无色", a["id"], "水的颜色是无色。", "claim1")
    second = svc.claim("水", "颜色", "蓝色", b["id"], "水的颜色是蓝色。", "claim2")
    assert second["id"] in svc.world()[0]["conflicts_with"]
    svc.source_review(a["id"], 1, "disputed", "证据不充分", None)
    assert not app.state.service.recall("水的颜色")["results"]
    assert not next(x for x in svc.world() if x["id"] == first["id"])["source_eligible"]
    assert any(j["status"] == "blocked" for j in svc.list("job"))
    with pytest.raises(Exception):
        svc.claim("水", "状态", "液态", a["id"], "水", "claim3")


def test_practice_review_required_before_mastery(env):
    app, c, svc = env
    r = svc.link("https://example.com", "材料", "l", lambda _: "植物需要水分。")
    while tick(app.state.db):
        pass
    course = svc.list("course")[0]
    path = "/v2/learning/courses/" + course["id"]
    assert (
        c.post(
            path + "/assess",
            json={"revision": course["revision"], "passed": True, "evidence": "看过"},
        ).status_code
        == 409
    )
    practice = svc.practice(
        course["id"], course["revision"], "植物需要水分。", "植物需要水分。", "p"
    )
    graded = svc.grade(practice["id"], 1, 4, "解释准确，但尚未验证迁移能力")
    assert graded["evaluation"] == "passed"
    assert (
        c.post(
            path + "/assess",
            json={
                "revision": course["revision"],
                "passed": True,
                "evidence": "人工核对练习",
            },
        ).status_code
        == 200
    )
    report = c.get(path + "/effect").json()
    assert report["latest_score"] == 4 and not report["generalization_verified"]


def test_failed_link_retry_does_not_fetch_again(env):
    app, c, svc = env

    def fail(_):
        raise ValueError("network problem")

    r = svc.link("https://example.com", "例子", "failed", fail)
    again = svc.link(
        "https://example.com",
        "例子",
        "failed",
        lambda _: pytest.fail("no automatic network retry"),
    )
    assert r["status"] == again["status"] == "failed"


def test_fetch_rejects_redirect_and_enforces_pin():
    from unittest.mock import MagicMock

    response = MagicMock()
    response.status = 302
    conn = MagicMock()
    conn.getresponse.return_value = response
    with (
        patch("fairy.link_fetch.public_addresses", return_value=["93.184.216.34"]),
        patch("fairy.link_fetch.PinnedHTTPS", return_value=conn) as pinned,
    ):
        with pytest.raises(ValueError, match="302"):
            fetch_text("https://example.com/")
        pinned.assert_called_once_with("example.com", "93.184.216.34")
        conn.close.assert_called_once()


def test_expired_source_no_longer_searchable_or_gradeable(env):
    app, c, svc = env
    r = svc.material("source", "植物需要水分。", "source")
    tick(app.state.db)
    source = r["material"]
    course = svc.list("course")[0]
    practice = svc.practice(
        course["id"], course["revision"], "答案", "植物需要水分。", "practice"
    )
    assert c.get("/v2/learning/search", params={"q": "植物"}).json()["results"]
    svc.source_review(
        source["id"], 1, "primary", "时效过期", "2000-01-01T00:00:00+00:00"
    )
    assert not c.get("/v2/learning/search", params={"q": "植物"}).json()["results"]
    with pytest.raises(Exception):
        svc.grade(practice["id"], 1, 5, "不能基于过期资料认证")
