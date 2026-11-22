"""Opt-in live cloud acceptance against the running Fairy API; needs a configured cloud key."""

import json
import os
import time
import uuid
from pathlib import Path

import httpx

from fairy.model_settings import CloudProfile, LocalProfile, ModelConfig


def main():
    base = os.getenv("FAIRY_API_URL", "http://127.0.0.1:8010").rstrip("/")
    token = os.getenv("FAIRY_API_TOKEN")
    if not token:
        token_file = Path.home() / "Library/Application Support/Fairy/api-token"
        if token_file.exists():
            token = token_file.read_text().strip()
    if not token:
        raise SystemExit(
            "Set FAIRY_API_TOKEN or create ~/Library/Application Support/Fairy/api-token"
        )
    output = Path(
        os.getenv("FAIRY_LIVE_REPORT", "docs/implementation/p1-cloud-acceptance.json")
    )
    c = httpx.Client(
        base_url=base + "/v2",
        headers={"Authorization": "Bearer " + token},
        timeout=240,
    )

    def ok(r):
        assert r.status_code == 200, (r.status_code, r.text)
        return r.json()

    def payload(data, **extra):
        body = {k: v for k, v in data.items() if k in ModelConfig.model_fields}
        body["local_profiles"] = [
            {k: v for k, v in p.items() if k in LocalProfile.model_fields}
            for p in data.get("local_profiles", [])
        ]
        body["cloud_profiles"] = [
            {
                k: v
                for k, v in p.items()
                if k in CloudProfile.model_fields
                and k not in ("key_configured", "ready")
            }
            for p in data.get("cloud_profiles", [])
        ]
        body.update(extra)
        return body

    def report(data):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(data, ensure_ascii=False), flush=True)

    conf = ok(c.get("/models/config"))
    ready = [p for p in conf["cloud_profiles"] if p["ready"]]
    profile = ready[0] if ready else None
    if not profile and not conf["cloud_ready"]:
        report(
            {
                "status": "skipped",
                "cloud_live_tested": False,
                "reason": "no_ready_cloud_config",
                "guidance": "请先在后台『模型与路由』填写云端 Base URL、模型与密钥并启用，再运行本脚本。",
            }
        )
        return

    original = payload(conf)
    routes = {t: dict(r) for t, r in conf["task_routes"].items()}
    routes["chat"]["cloud"] = profile["id"] if profile else "default"
    checks = []
    results = []
    budget_after = None
    try:
        ok(
            c.put(
                "/models/config",
                json=payload(conf, task_routes=routes, smart_task_routing=False),
            )
        )
        budget_before = ok(c.get("/models/budget"))

        def turn(text, key):
            start = time.monotonic()
            data = ok(
                c.post(
                    "/turns",
                    json={"text": text, "routing": "cloud_assist"},
                    headers={"Idempotency-Key": key},
                )
            )
            print(
                json.dumps(
                    {
                        "step": key,
                        "status": data["status"],
                        "error": data.get("error"),
                        "reply": data.get("reply"),
                        "cloud_used": data["model_route"]["cloud_used"],
                        "cloud_skip_reason": data["model_route"].get(
                            "cloud_skip_reason"
                        ),
                        "seconds": round(time.monotonic() - start, 2),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            assert data["status"] == "completed", data
            results.append({"step": key, "input": text, "reply": data.get("reply")})
            return data

        first = turn(
            "云端验收：请只回复『云端链路正常』六个字。",
            "cloud-acceptance-" + uuid.uuid4().hex[:12],
        )
        route = first["model_route"]
        assert route["cloud_used"] and route["provider"] == "cloud", route
        checks.append("cloud_assist turn answered by the real cloud provider")
        calls = ok(c.get("/models/invocations"))
        rows = [
            row
            for row in calls
            if row["turn_id"] == first["id"] and row["phase"] == "cloud"
        ]
        assert len(rows) == 1 and rows[0]["charge_status"] == "settled", rows
        checks.append("cloud invocation settled with a recorded cost")
        budget_after = ok(c.get("/models/budget"))
        assert budget_after["requests"] >= budget_before["requests"] + 1, budget_after
        checks.append("daily budget counted the cloud request")

        ok(
            c.put(
                "/models/config",
                json=payload(
                    ok(c.get("/models/config")),
                    cloud_daily_request_limit=min(budget_after["requests"], 1000),
                ),
            )
        )
        capped = turn(
            "云端验收：限额测试，请回复收到。",
            "cloud-cap-" + uuid.uuid4().hex[:12],
        )
        assert not capped["model_route"]["cloud_used"], capped["model_route"]
        assert (
            capped["model_route"].get("cloud_skip_reason")
            == "cloud_daily_limit_reached"
        ), capped["model_route"]
        checks.append("daily request cap blocks further cloud calls")
    finally:
        try:
            fresh = ok(c.get("/models/config"))
            restore = payload(fresh)
            for field in (
                "task_routes",
                "smart_task_routing",
                "cloud_daily_request_limit",
            ):
                restore[field] = original[field]
            ok(c.put("/models/config", json=restore))
        except Exception as e:
            print("警告：恢复模型配置失败，请到后台核对：" + repr(e), flush=True)

    report(
        {
            "status": "passed",
            "api": base,
            "profile": profile["name"] if profile else "默认（顶层配置）",
            "cloud_model": profile["model"] if profile else conf["cloud_model"],
            "checks": checks,
            "results": results,
            "budget": budget_after,
            "cloud_live_tested": True,
        }
    )
    print("Live cloud acceptance passed", flush=True)


if __name__ == "__main__":
    main()
