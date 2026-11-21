"""Optional local Ollama embeddings with durable content-addressed caching."""

from __future__ import annotations

import hashlib
import json
import math
import os

import httpx

from .store import Record, now


def cosine(left, right):
    if len(left) != len(right) or not left:
        return 0.0
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return numerator / (left_norm * right_norm)


class SemanticService:
    def __init__(self, db, settings, transport=None):
        self.db = db
        self.settings = settings
        self.transport = transport

    def configuration(self):
        runtime = self.settings.runtime()
        model = os.getenv("FAIRY_EMBEDDING_MODEL", "bge-m3:latest")
        return {
            "enabled": bool(model),
            "provider": "ollama",
            "model": model,
            "base_url": runtime["ollama_base_url"],
            "cache": "records",
            "cloud_used": False,
        }

    @staticmethod
    def _cache_key(model, text):
        return model + ":" + hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _cache_id(key):
        # Primary-key lookup avoids scanning a growing cache window per query.
        return "embed:" + key

    def _cached(self, session, keys):
        found = {}
        for key in keys:
            row = session.get(Record, self._cache_id(key))
            if not row or row.status != "active":
                continue
            vector = json.loads(row.payload).get("vector")
            if (
                isinstance(vector, list)
                and len(vector) <= 4096
                and all(isinstance(value, (int, float)) for value in vector)
            ):
                found[key] = vector
        return found

    async def embeddings(self, texts):
        config = self.configuration()
        if not config["enabled"] or not texts:
            return None
        unique = list(dict.fromkeys(texts))
        keys = {text: self._cache_key(config["model"], text) for text in unique}
        vectors = {}
        with self.db.sessions() as session:
            cached = self._cached(session, set(keys.values()))
            for text in unique:
                if keys[text] in cached:
                    vectors[text] = cached[keys[text]]
        missing = [text for text in unique if text not in vectors]
        if missing:
            try:
                async with httpx.AsyncClient(
                    timeout=min(
                        self.settings.runtime()["local_timeout_seconds"],
                        120,
                    ),
                    transport=self.transport,
                    follow_redirects=False,
                    trust_env=False,
                ) as client:
                    response = await client.post(
                        config["base_url"] + "/api/embed",
                        json={"model": config["model"], "input": missing},
                    )
                    response.raise_for_status()
                    payload = response.json()
            except (httpx.HTTPError, ValueError):
                return None
            embeddings = payload.get("embeddings")
            if (
                not isinstance(embeddings, list)
                or len(embeddings) != len(missing)
                or any(not isinstance(vector, list) for vector in embeddings)
            ):
                return None
            with self.db.tx() as session:
                for text, vector in zip(missing, embeddings):
                    if len(vector) > 4096:
                        return None
                    vectors[text] = vector
                    session.add(
                        Record(
                            id=self._cache_id(keys[text]),
                            scope="owner",
                            kind="embedding_cache",
                            revision=1,
                            status="active",
                            payload=json.dumps(
                                {
                                    "key": keys[text],
                                    "model": config["model"],
                                    "vector": vector,
                                },
                                ensure_ascii=False,
                            ),
                            created_at=now(),
                        )
                    )
        return [vectors[text] for text in texts]

    async def rerank(self, query, documents):
        if not documents:
            return None
        values = await self.embeddings([query] + [item["text"] for item in documents])
        if values is None or len(values) != len(documents) + 1:
            return None
        query_vector, candidates = values[0], values[1:]
        return [
            dict(item, semantic_relevance=cosine(query_vector, vector))
            for item, vector in zip(documents, candidates)
        ]
