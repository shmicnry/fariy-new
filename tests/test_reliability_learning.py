import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from fairy.store import Store
from fairy.app import create_app
from fairy.service import Service
from fairy.worker import tick
from fairy.maintenance import copy_database


def test_concurrent_bootstrap_and_migration(tmp_path):
    url = "sqlite:///" + str(tmp_path / "db.sqlite")
    with ThreadPoolExecutor(6) as pool:
        stores = list(pool.map(lambda _: Store(url), range(6)))
    with stores[0].engine.connect() as c:
        assert c.execute(text("SELECT version FROM schema_version")).scalar() == 2
        assert c.execute(text("SELECT count(*) FROM scope_locks")).scalar() == 1
    Service(stores[0]).custom_card("persisted", "content", "note", None, "one")
    assert Service(Store(url)).list("card")[0]["title"] == "persisted"


def test_future_schema_refused(tmp_path):
    path = tmp_path / "future.db"
    Store("sqlite:///" + str(path))
    with sqlite3.connect(path) as c:
        c.execute("UPDATE schema_version SET version=999")
    with pytest.raises(RuntimeError, match="newer"):
        Store("sqlite:///" + str(path))


def test_snapshot_restore_retains_memory_and_no_overwrite(tmp_path):
    path = tmp_path / "source.db"
    app = create_app("sqlite:///" + str(path), token="test")
    source = app.state.service.material("source", "我喜欢喝温水", "m")["material"]
    memory = app.state.service.memory("我喜欢喝温水", [source["id"]], "mem")
    app.state.service.correct(memory["id"], 1, "我喜欢喝茶", "修改", "edit")
    backup = tmp_path / "backup.db"
    report = copy_database(path, backup)
    assert backup.stat().st_mode & 0o777 == 0o600
    restored = tmp_path / "restore.db"
    copy_database(backup, restored, report["sha256"])
    svc = create_app("sqlite:///" + str(restored), token="test").state.service
    assert svc.list("memory")[0]["text"] == "我喜欢喝茶"
    assert len(svc.history(memory["id"])) == 2
    with pytest.raises(ValueError, match="already_exists"):
        copy_database(backup, restored)
    with pytest.raises(ValueError, match="digest"):
        copy_database(backup, tmp_path / "bad.db", "wrong")


def test_legacy_database_upgrade(tmp_path):
    p = tmp_path / "legacy.db"
    db = Store("sqlite:///" + str(p))
    Service(db).custom_card("old", "v0.2", "note", None, "old")
    with sqlite3.connect(p) as c:
        c.execute("DROP TABLE schema_version")
    assert Service(Store("sqlite:///" + str(p))).list("card")[0]["title"] == "old"


def client(tmp_path):
    a = create_app("sqlite:///" + str(tmp_path / "learn.db"), token="test")
    c = TestClient(a)
    c.headers["Authorization"] = "Bearer test"
    return a, c


def upload(c, text="第一段。" * 1000, key="upload", filename="知识.md"):
    return c.post(
        "/v2/learning/files",
        json={
            "filename": filename,
            "content_base64": base64.b64encode(text.encode()).decode(),
        },
        headers={"Idempotency-Key": key},
    )


def test_file_chunks_restart_practice_and_delete(tmp_path):
    app, c = client(tmp_path)
    r = upload(c).json()
    course = r["course"]["id"]
    assert r["chunk_count"] > 1
    assert upload(c).json()["material"]["id"] == r["material"]["id"]
    assert tick(app.state.db)
    reopened = Store(str(app.state.db.engine.url))
    while tick(reopened):
        pass
    parts = c.get("/v2/learning/courses/" + course + "/chunks").json()
    assert "".join(p["text"] for p in parts) == "第一段。" * 1000
    assert [p["start"] for p in parts] == list(range(0, len("第一段。" * 1000), 1200))
    current = c.get("/v2/learning/courses").json()[0]
    assert current["stage"] == "awaiting_assessment" and not current["mastered"]
    response = c.post(
        "/v2/learning/courses/" + course + "/practice",
        json={
            "revision": current["revision"],
            "answer": "我的理解",
            "evidence": "第一段。",
        },
        headers={"Idempotency-Key": "practice"},
    )
    assert response.status_code == 200 and response.json()["evaluation"] == "ungraded"
    bad = c.post(
        "/v2/learning/courses/" + course + "/practice",
        json={
            "revision": current["revision"],
            "answer": "答案",
            "evidence": "编造出处",
        },
        headers={"Idempotency-Key": "bad"},
    )
    assert bad.status_code == 422
    c.delete("/v2/records/" + r["material"]["id"] + "?revision=1")
    assert not c.get("/v2/learning/courses/" + course + "/chunks").json()
    assert not c.get("/v2/learning/courses/" + course + "/practice").json()


@pytest.mark.parametrize(
    "name,content,code",
    [
        ("../file.txt", "a", 422),
        ("run.py", "print(1)", 415),
        ("x.txt", "\x00", 422),
        ("empty.md", " ", 422),
    ],
)
def test_invalid_uploads(tmp_path, name, content, code):
    app, c = client(tmp_path)
    assert upload(c, content, filename=name).status_code == code


def test_postgres_bootstrap_and_concurrent_writes(tmp_path):
    url = os.getenv("FAIRY_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("requires disposable Postgres database")
    with ThreadPoolExecutor(4) as pool:
        stores = list(pool.map(lambda _: Store(url), range(4)))
    svc = Service(stores[0])
    with ThreadPoolExecutor(4) as pool:
        rows = list(
            pool.map(
                lambda _: svc.custom_card("PG", "concurrent", "note", None, "pg-same"),
                range(4),
            )
        )
    assert len(set(r["id"] for r in rows)) == 1
    app = create_app(url, token="test", secrets_dir=tmp_path / "credentials")
    service = app.state.service
    source = service.material("source", "我喜欢喝温水", "pg-mat")["material"]
    m = service.memory("我喜欢喝温水", [source["id"]], "pg-memory")
    corrected = service.correct(
        m["id"], m["revision"], "我喜欢喝茶", "更正", "pg-correct"
    )
    assert len(service.history(m["id"])) == 2
    service.invalidate(m["id"], corrected["revision"])
    assert not service.list("memory")
