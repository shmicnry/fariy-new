"""Opt-in live acceptance: synthetic data, an isolated DB, and local-only model calls."""

import json
import os
import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient
from fairy.app import create_app


def main():
    output = Path(
        os.getenv("FAIRY_LIVE_REPORT", "docs/implementation/p1-ollama-acceptance.json")
    )
    with tempfile.TemporaryDirectory(prefix="fairy-p1-live-") as directory:
        app = create_app(
            "sqlite:///" + str(Path(directory) / "live.db"),
            token="isolated-live-acceptance",
            secrets_dir=Path(directory) / "credentials",
        )
        c = TestClient(app)
        c.headers["Authorization"] = "Bearer isolated-live-acceptance"
        installed = c.get("/v2/models/ollama").json()
        assert installed["reachable"] and installed["selected_installed"], installed
        results = []

        def turn(text, key):
            start = time.monotonic()
            r = c.post(
                "/v2/turns",
                json={"text": text, "routing": "local_only"},
                headers={"Idempotency-Key": key},
            )
            assert r.status_code == 200, r.text
            data = r.json()
            print(
                json.dumps(
                    {
                        "step": key,
                        "status": data["status"],
                        "error": data.get("error"),
                        "reply": data.get("reply"),
                        "seconds": round(time.monotonic() - start, 2),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            assert data["status"] == "completed", data
            assert (
                data["model_route"]["provider"] == "ollama"
                and not data["model_route"]["cloud_used"]
            )
            results.append(
                {
                    "step": key,
                    "input": text,
                    "reply": data["reply"],
                    "model": data["model_route"]["model"],
                    "question_subject": data["model_route"].get("question_subject"),
                    "answer_basis": data["model_route"].get("answer_basis"),
                    "used_memory_ids": data["model_route"].get("used_memory_ids", []),
                }
            )
            return data

        first = turn("请记住，我喜欢喝茉莉花茶。", "statement")
        assert c.get("/v2/memories").json() == []
        assert "我喜欢喝" not in first["reply"] and "待审阅" in first["reply"]
        proposals = [
            p
            for p in c.get("/v2/memory/proposals").json()
            if p["id"] in first["memory_proposal_ids"] and "茉莉花茶" in p["text"]
        ]
        assert proposals, "The real model did not propose the explicit preference"
        proposal = proposals[0]
        r = c.post(
            "/v2/memory/proposals/" + proposal["id"] + "/review",
            json={"revision": proposal["revision"], "decision": "approve"},
            headers={"Idempotency-Key": "approve"},
        )
        assert r.status_code == 200, r.text
        memory = c.get("/v2/memories").json()[0]
        recalled = turn("我喜欢喝什么？", "recall")
        assert "茉莉花茶" in recalled["reply"]
        assert recalled["model_route"]["answer_basis"] == "confirmed_memory"
        assert memory["id"] in recalled["model_route"]["used_memory_ids"]
        assert "我喜欢" not in recalled["reply"]
        r = c.patch(
            "/v2/memories/" + memory["id"],
            json={
                "revision": memory["revision"],
                "text": "我现在喜欢喝温水。",
                "reason": "合成验收中的偏好变更",
            },
            headers={"Idempotency-Key": "correct"},
        )
        assert r.status_code == 200, r.text
        corrected = r.json()
        next_answer = turn("我喜欢喝什么？", "corrected_recall")
        assert "温水" in next_answer["reply"] and "茉莉花茶" not in next_answer["reply"]
        restarted = create_app(
            str(app.state.db.engine.url),
            token="isolated-live-acceptance",
            secrets_dir=Path(directory) / "credentials",
        )
        assert (
            restarted.state.service.recall("温水")["results"][0]["text"]
            == "我现在喜欢喝温水。"
        )
        assert len(c.get("/v2/memories/" + memory["id"] + "/history").json()) == 2
        assert (
            c.delete(
                "/v2/memories/"
                + memory["id"]
                + "?revision="
                + str(corrected["revision"])
            ).status_code
            == 200
        )
        context, _ = app.state.service.model_context("我喜欢喝什么")
        assert "茉莉花茶" not in json.dumps(
            context, ensure_ascii=False
        ) and "温水" not in json.dumps(context, ensure_ascii=False)
        forgotten = turn(
            "我喜欢喝什么？如果没有我的记录，请直接说明不知道。", "after_forget"
        )
        assert "茉莉花茶" not in forgotten["reply"] and "温水" not in forgotten["reply"]
        assert forgotten["model_route"]["question_subject"] == "owner"
        assert forgotten["model_route"]["answer_basis"] == "no_confirmed_memory"
        assert "用户询问我" not in forgotten["reply"]
        assistant = turn("你喜欢喝什么？", "assistant_preference")
        assert assistant["model_route"]["question_subject"] == "assistant"
        assert assistant["model_route"]["answer_basis"] == "assistant_identity"
        calls = c.get("/v2/models/invocations").json()
        assert all(row["phase"] == "local" for row in calls)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(
                {
                    "status": "passed",
                    "primary_provider": "ollama",
                    "model": installed["selected"],
                    "synthetic_data": True,
                    "final_answer_policy": "source-grounded expression for supported personal preference questions",
                    "raw_model_draft_quality_claimed": False,
                    "scenario": {
                        "initial_owner_statement": "请记住，我喜欢喝茉莉花茶。",
                        "later_owner_correction": "我现在喜欢喝温水。",
                        "assertions_are_time_ordered": True,
                        "personal_recall_excludes_recent_dialogue": True,
                    },
                    "checks": [
                        "real native inference",
                        "automatic exact-quote proposal",
                        "review before recall",
                        "approved recall",
                        "corrected recall",
                        "version history",
                        "restart persistence",
                        "forget removes historical context",
                        "post-forget reply",
                        "no cloud request",
                    ],
                    "results": results,
                    "local_invocations": len(calls),
                    "cloud_live_tested": False,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )
        print("Live Ollama acceptance passed", flush=True)


if __name__ == "__main__":
    main()
