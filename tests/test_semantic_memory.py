import hashlib
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from fairy.app import create_app
from fairy.cognition import relevance
from fairy.store import Record
from tests.db import postgres_url


def embed_handler(request):
    payload = json.loads(request.content)
    vectors = []
    for text in payload["input"]:
        vectors.append([1.0, 0.0] if ("温水" in text or "饮品" in text) else [0.0, 1.0])
    return httpx.Response(200, json={"embeddings": vectors})


@pytest.fixture
def semantic_app(tmp_path, monkeypatch):
    monkeypatch.setenv("FAIRY_EMBEDDING_MODEL", "test-embedding")
    app = create_app(
        postgres_url(tmp_path),
        token="owner",
        transport=httpx.MockTransport(embed_handler),
    )
    client = TestClient(app)
    client.headers["Authorization"] = "Bearer owner"
    svc = app.state.service
    mat = svc.material("偏好", "我喜欢喝温水", "mat")["material"]
    memory = svc.memory("我喜欢喝温水", [mat["id"]], "m")
    return app, client, memory


def embedding_hashes(app):
    with app.state.db.sessions() as s:
        rows = s.scalars(select(Record).where(Record.kind == "embedding_cache")).all()
    return {json.loads(r.payload)["key"].rsplit(":", 1)[-1] for r in rows}


def test_semantic_recall_surfaces_paraphrase(semantic_app):
    app, client, memory = semantic_app
    # The query shares no characters with the memory, so lexical recall alone misses it.
    assert relevance("饮品偏好", "我喜欢喝温水") < 0.25
    body = client.get("/v2/memories?q=饮品偏好").json()
    assert body["semantic_available"] is True and body["degraded"] is False
    assert body["retrieval_mode"] == "ollama_semantic_rerank_with_local_character_fallback"
    assert memory["id"] in [r["id"] for r in body["results"]]


def test_fallback_when_embeddings_unavailable(tmp_path, monkeypatch):
    monkeypatch.setenv("FAIRY_EMBEDDING_MODEL", "test-embedding")

    def failing(request):
        return httpx.Response(500)

    app = create_app(
        postgres_url(tmp_path), token="owner", transport=httpx.MockTransport(failing)
    )
    client = TestClient(app)
    client.headers["Authorization"] = "Bearer owner"
    svc = app.state.service
    mat = svc.material("偏好", "我喜欢喝温水", "mat")["material"]
    svc.memory("我喜欢喝温水", [mat["id"]], "m")
    body = client.get("/v2/memories?q=温水").json()
    assert body["degraded"] is True
    assert body["retrieval_mode"] == "local_character_vector_hybrid"
    assert body["results"] and body["results"][0]["text"] == "我喜欢喝温水"


def test_forget_purges_embedding_cache(semantic_app):
    app, client, memory = semantic_app
    client.get("/v2/memories?q=饮品偏好")
    text_hash = hashlib.sha256("我喜欢喝温水".encode("utf-8")).hexdigest()
    assert text_hash in embedding_hashes(app)
    app.state.service.invalidate(memory["id"], memory["revision"])
    assert text_hash not in embedding_hashes(app)
    assert client.get("/v2/memories?q=饮品偏好").json()["results"] == []


def test_correct_purges_old_text_embedding(semantic_app):
    app, client, memory = semantic_app
    client.get("/v2/memories?q=饮品偏好")
    old_hash = hashlib.sha256("我喜欢喝温水".encode("utf-8")).hexdigest()
    assert old_hash in embedding_hashes(app)
    resp = client.patch(
        "/v2/memories/" + memory["id"],
        json={"revision": memory["revision"], "text": "我现在喜欢喝温水", "reason": "更准确"},
        headers={"Idempotency-Key": "correct-1"},
    )
    assert resp.status_code == 200, resp.text
    assert old_hash not in embedding_hashes(app)


def test_model_context_accepts_prerecalled(semantic_app):
    app, client, memory = semantic_app
    recalled = client.get("/v2/memories?q=饮品偏好").json()["results"]
    context, snapshot = app.state.service.model_context("饮品偏好", recalled=recalled)
    assert memory["id"] in [e["id"] for e in context["entries"] if e["kind"] == "quoted_memory"]
    assert memory["id"] in snapshot


def test_capability_mode_reflects_semantic_config(semantic_app, tmp_path, monkeypatch):
    app, client, _ = semantic_app
    assert (
        client.get("/v2/capabilities").json()["vector_search_mode"]
        == "ollama_semantic_rerank_with_local_character_fallback"
    )
    monkeypatch.setenv("FAIRY_EMBEDDING_MODEL", "")
    plain = create_app(postgres_url(tmp_path), token="owner")
    plain_client = TestClient(plain)
    plain_client.headers["Authorization"] = "Bearer owner"
    assert (
        plain_client.get("/v2/capabilities").json()["vector_search_mode"]
        == "local_character_vector_hybrid"
    )
