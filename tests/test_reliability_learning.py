import base64
from concurrent.futures import ThreadPoolExecutor
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from fairy.app import create_app
from fairy.maintenance import backup_database, restore_database
from fairy.service import Service
from fairy.store import Store
from fairy.worker import tick
from tests.db import postgres_database, postgres_url


def test_non_postgresql_database_is_rejected():
    with pytest.raises(ValueError, match="postgresql_database_required"):
        Store("sqlite:///unsupported.db")


def test_concurrent_bootstrap_and_migration(tmp_path):
    url = postgres_url(tmp_path)
    with ThreadPoolExecutor(6) as pool:
        stores = list(pool.map(lambda _: Store(url), range(6)))
    with stores[0].engine.connect() as connection:
        assert (
            connection.execute(text("SELECT version FROM schema_version")).scalar()
            == 2
        )
        assert (
            connection.execute(text("SELECT count(*) FROM scope_locks")).scalar() == 1
        )
    Service(stores[0]).custom_card("persisted", "content", "note", None, "one")
    assert Service(Store(url)).list("card")[0]["title"] == "persisted"


def test_future_schema_refused(tmp_path):
    url = postgres_url(tmp_path)
    store = Store(url)
    with store.engine.begin() as connection:
        connection.execute(text("UPDATE schema_version SET version=999 WHERE id=1"))
    with pytest.raises(RuntimeError, match="newer"):
        Store(url)


def test_postgres_backup_restore_and_digest(tmp_path):
    source_url = postgres_database()
    target_url = postgres_database()
    app = create_app(source_url, token="test")
    source = app.state.service.material(
        "source", "我喜欢喝温水", "m"
    )["material"]
    memory = app.state.service.memory(
        "我喜欢喝温水", [source["id"]], "mem"
    )
    app.state.service.correct(
        memory["id"], 1, "我喜欢喝茶", "修改", "edit"
    )
    backup = tmp_path / "backup.dump"
    report = backup_database(source_url, backup)
    assert backup.stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError, match="already_exists"):
        backup_database(source_url, backup)
    with pytest.raises(ValueError, match="digest"):
        restore_database(backup, target_url, "wrong")
    restored = restore_database(backup, target_url, report["sha256"])
    assert restored["restored"] is True
    service = create_app(target_url, token="test").state.service
    assert service.list("memory")[0]["text"] == "我喜欢喝茶"
    assert len(service.history(memory["id"])) == 2


def client(tmp_path):
    app = create_app(postgres_url(tmp_path), token="test")
    client = TestClient(app)
    client.headers["Authorization"] = "Bearer test"
    return app, client


def upload(client, text_value="第一段。" * 1000, key="upload", filename="知识.md"):
    return client.post(
        "/v2/learning/files",
        json={
            "filename": filename,
            "content_base64": base64.b64encode(text_value.encode()).decode(),
        },
        headers={"Idempotency-Key": key},
    )


def test_file_chunks_restart_practice_and_delete(tmp_path):
    app, client_instance = client(tmp_path)
    response = upload(client_instance).json()
    course = response["course"]["id"]
    assert response["chunk_count"] > 1
    assert (
        upload(client_instance).json()["material"]["id"]
        == response["material"]["id"]
    )
    assert tick(app.state.db)
    reopened = Store(str(app.state.db.engine.url))
    while tick(reopened):
        pass
    parts = client_instance.get(
        "/v2/learning/courses/" + course + "/chunks"
    ).json()
    assert "".join(part["text"] for part in parts) == "第一段。" * 1000
    assert [part["start"] for part in parts] == list(
        range(0, len("第一段。" * 1000), 1200)
    )
    current = client_instance.get("/v2/learning/courses").json()[0]
    assert current["stage"] == "awaiting_assessment" and not current["mastered"]
    practice = client_instance.post(
        "/v2/learning/courses/" + course + "/practice",
        json={
            "revision": current["revision"],
            "answer": "我的理解",
            "evidence": "第一段。",
        },
        headers={"Idempotency-Key": "practice"},
    )
    assert practice.status_code == 200
    assert practice.json()["evaluation"] == "ungraded"
    bad = client_instance.post(
        "/v2/learning/courses/" + course + "/practice",
        json={
            "revision": current["revision"],
            "answer": "答案",
            "evidence": "编造出处",
        },
        headers={"Idempotency-Key": "bad"},
    )
    assert bad.status_code == 422
    client_instance.delete(
        "/v2/records/" + response["material"]["id"] + "?revision=1"
    )
    assert not client_instance.get(
        "/v2/learning/courses/" + course + "/chunks"
    ).json()
    assert not client_instance.get(
        "/v2/learning/courses/" + course + "/practice"
    ).json()


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
    app, client_instance = client(tmp_path)
    assert upload(client_instance, content, filename=name).status_code == code


def test_postgres_bootstrap_and_concurrent_writes(tmp_path):
    url = postgres_url(tmp_path)
    with ThreadPoolExecutor(4) as pool:
        stores = list(pool.map(lambda _: Store(url), range(4)))
    service = Service(stores[0])
    with ThreadPoolExecutor(4) as pool:
        rows = list(
            pool.map(
                lambda _: service.custom_card(
                    "PG", "concurrent", "note", None, "pg-same"
                ),
                range(4),
            )
        )
    assert len(set(row["id"] for row in rows)) == 1
    app = create_app(
        url, token="test", secrets_dir=tmp_path / "credentials"
    )
    service = app.state.service
    source = service.material(
        "source", "我喜欢喝温水", "pg-mat"
    )["material"]
    memory = service.memory(
        "我喜欢喝温水", [source["id"]], "pg-memory"
    )
    corrected = service.correct(
        memory["id"], memory["revision"], "我喜欢喝茶", "更正", "pg-correct"
    )
    assert len(service.history(memory["id"])) == 2
    service.invalidate(memory["id"], corrected["revision"])
    assert not service.list("memory")
