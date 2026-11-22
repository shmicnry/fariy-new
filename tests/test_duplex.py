"""Full-duplex voice: VAD, WebSocket protocol, barge-in vs backchannel,
background work delivery lifecycle, restart recovery, and contrast-based
evolution composition (ideas absorbed from Realtime-Venus / Harness2)."""
import struct
import time

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from fairy.app import create_app
from fairy.duplex import EnergyVad, split_sentences, wav_wrap
from tests.db import postgres_url
from tests.test_p1 import local, post


def frame(amp: int) -> bytes:
    return struct.pack("<h", amp) * 320  # one 20ms PCM16LE mono frame @16kHz


LOUD = frame(3000)
SILENT = frame(0)


@pytest.fixture
def factory(tmp_path, monkeypatch):
    monkeypatch.setenv("FAIRY_OLLAMA_MODEL", "fixture")
    url = postgres_url(tmp_path)  # one schema per test; restart test shares it

    def make(handler=None):
        app = create_app(
            url,
            token="test",
            transport=httpx.MockTransport(handler or (lambda req: local())),
        )
        c = TestClient(app)
        c.headers["Authorization"] = "Bearer test"
        return app, c

    return make


def fake_voice(app, transcript="我喜欢温水"):
    app.state.voice.speak = lambda text: b"RIFFfake"
    app.state.voice.transcribe = lambda body: {"text": transcript}


def auth(ws):
    ws.send_json({"type": "auth", "token": "test"})
    ready = ws.receive_json()
    assert ready["type"] == "ready"
    return ready


def drain(ws, predicate, cap=60):
    seen = []
    for _ in range(cap):
        msg = ws.receive_json()
        seen.append(msg)
        if predicate(msg):
            return msg, seen
    raise AssertionError(f"predicate never matched; saw {seen}")


def is_state(state):
    return lambda m: m.get("type") == "state" and m.get("state") == state


def wait_work(c, work_id, state, timeout=8.0):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        r = c.get("/v2/duplex/works")
        assert r.status_code == 200
        last = r.json()
        for view in last:
            if view["id"] == work_id and view.get("state") == state:
                return view
        time.sleep(0.05)
    raise AssertionError(f"work {work_id} never reached {state}; last={last}")


# ---------- unit: VAD / sentence splitting / WAV ----------

def test_vad_onset_offset_and_discard():
    vad = EnergyVad()
    assert vad.push(SILENT * 10) == []
    assert vad.push(LOUD * 15) == [{"event": "speech_start", "duration_ms": 40}]
    assert vad.push(SILENT * 35) == [
        {"event": "speech_end", "duration_ms": 900, "voiced_ms": 300}
    ]
    short = EnergyVad()
    assert short.push(LOUD * 5) == [{"event": "speech_start", "duration_ms": 40}]
    assert short.push(SILENT * 35) == [
        {"event": "speech_discarded", "duration_ms": 700, "voiced_ms": 100}
    ]


def test_vad_buffers_partial_frames():
    vad = EnergyVad()
    assert vad.push(LOUD[:320]) == []
    assert vad.push(LOUD[320:] + LOUD * 2) == [
        {"event": "speech_start", "duration_ms": 40}
    ]


def test_split_sentences_and_wav():
    assert split_sentences("本地回答") == ["本地回答"]
    assert [len(s) for s in split_sentences("a" * 300)] == [120, 120, 60]
    assert split_sentences("Hello world. This is a test sentence.") == [
        "Hello world.", "This is a test sentence."
    ]
    assert split_sentences("好。好的。") == ["好。好的。"]
    assert split_sentences("") == []
    assert len(wav_wrap(b"\x00\x01\x02")) == 46  # odd tail dropped, 44-byte header


# ---------- WebSocket auth ----------

def test_ws_rejects_wrong_token(factory):
    _, c = factory()
    with c:
        with pytest.raises(WebSocketDisconnect) as exc:
            with c.websocket_connect("/v2/duplex/ws") as ws:
                ws.send_json({"type": "auth", "token": "wrong"})
                ws.receive_json()
        assert exc.value.code == 4401


def test_ws_requires_auth_first(factory):
    _, c = factory()
    with c:
        with pytest.raises(WebSocketDisconnect) as exc:
            with c.websocket_connect("/v2/duplex/ws") as ws:
                ws.send_json({"type": "text", "text": "你好"})
                ws.receive_json()
        assert exc.value.code == 4401


def test_ws_rejects_foreign_origin(factory):
    _, c = factory()
    with c:
        with pytest.raises(WebSocketDisconnect) as exc:
            with c.websocket_connect(
                "/v2/duplex/ws", headers={"origin": "http://evil.example"}
            ) as ws:
                ws.send_json({"type": "auth", "token": "test"})
                ws.receive_json()
        assert exc.value.code == 4403


def test_ws_ready_and_protocol_edges(factory):
    app, c = factory()
    fake_voice(app)
    with c:
        with c.websocket_connect("/v2/duplex/ws") as ws:
            ready = auth(ws)
            assert ready["session_id"].startswith("dx-")
            assert ready["state"] == "idle"
            assert ready["capabilities"]["barge_in"] is True
            ws.send_json({"type": "ping"})
            assert ws.receive_json()["type"] == "pong"
            ws.send_json({"type": "text", "text": "  "})
            msg, _ = drain(ws, lambda m: m.get("type") == "error")
            assert msg["detail"] == "empty_text"
            ws.send_json({"type": "nonsense"})
            msg, _ = drain(ws, lambda m: m.get("type") == "error")
            assert msg["detail"] == "unknown_message_type"
            ws.send_bytes(b"\x00" * 65537)
            msg, _ = drain(ws, lambda m: m.get("type") == "error")
            assert msg["detail"] == "audio_chunk_too_large"


# ---------- turns ----------

def test_text_turn_speech_and_ack(factory):
    app, c = factory()
    fake_voice(app)
    with c:
        with c.websocket_connect("/v2/duplex/ws") as ws:
            auth(ws)
            ws.send_json({"type": "text", "text": "你好"})
            reply, seen = drain(ws, lambda m: m.get("type") == "reply")
            assert reply["text"] == "本地回答"
            assert reply["turn_id"]
            assert any(is_state("thinking")(m) for m in seen)
            speech, seen = drain(ws, lambda m: m.get("type") == "speech")
            assert speech["kind"] == "reply"
            assert speech["total"] == 1 and speech["final"] is True
            assert speech["audio_base64"] is not None
            assert any(is_state("speaking")(m) for m in seen)
            ws.send_json({
                "type": "playback_ack", "item_id": speech["item_id"],
                "seq": 0, "played": True,
            })
            drain(ws, is_state("idle"))


def test_tts_failure_falls_back_to_text(factory):
    app, c = factory()
    fake_voice(app)

    def broken_speak(text):
        raise HTTPException(503, "local_tts_unavailable")

    app.state.voice.speak = broken_speak
    with c:
        with c.websocket_connect("/v2/duplex/ws") as ws:
            auth(ws)
            ws.send_json({"type": "text", "text": "你好"})
            speech, _ = drain(ws, lambda m: m.get("type") == "speech")
            assert speech["audio_base64"] is None
            assert speech["text"] == "本地回答"
            ws.send_json({
                "type": "playback_ack", "item_id": speech["item_id"],
                "seq": 0, "played": True,
            })
            drain(ws, is_state("idle"))


def test_audio_turn_transcribes_and_answers(factory):
    app, c = factory()
    fake_voice(app)
    with c:
        with c.websocket_connect("/v2/duplex/ws") as ws:
            auth(ws)
            ws.send_bytes(LOUD * 15)
            _, seen = drain(
                ws, lambda m: m.get("type") == "vad" and m.get("event") == "speech_start"
            )
            assert any(is_state("listening")(m) for m in seen)
            ws.send_bytes(SILENT * 35)
            end, _ = drain(
                ws, lambda m: m.get("type") == "vad" and m.get("event") == "speech_end"
            )
            assert end["voiced_ms"] == 300
            transcript, _ = drain(ws, lambda m: m.get("type") == "transcript")
            assert transcript["text"] == "我喜欢温水"
            reply, _ = drain(ws, lambda m: m.get("type") == "reply")
            assert reply["text"] == "本地回答"
            speech, _ = drain(ws, lambda m: m.get("type") == "speech")
            ws.send_json({
                "type": "playback_ack", "item_id": speech["item_id"],
                "seq": 0, "played": True,
            })
            drain(ws, is_state("idle"))


def test_asr_failure_returns_idle(factory):
    app, c = factory()
    fake_voice(app)

    def broken_transcribe(body):
        raise HTTPException(503, "local_asr_not_configured")

    app.state.voice.transcribe = broken_transcribe
    with c:
        with c.websocket_connect("/v2/duplex/ws") as ws:
            auth(ws)
            ws.send_bytes(LOUD * 15)
            ws.send_bytes(SILENT * 35)
            err, _ = drain(ws, lambda m: m.get("type") == "asr_error")
            assert err["detail"] == "local_asr_not_configured"
            drain(ws, is_state("idle"))


def test_short_burst_is_backchannel_not_barge_in(factory):
    app, c = factory()
    fake_voice(app)
    with c:
        with c.websocket_connect("/v2/duplex/ws") as ws:
            auth(ws)
            ws.send_json({"type": "text", "text": "你好"})
            speech, _ = drain(ws, lambda m: m.get("type") == "speech")
            for _ in range(5):  # 100ms voiced burst, below the 500ms threshold
                ws.send_bytes(LOUD)
            for _ in range(7):
                ws.send_bytes(SILENT * 5)
            back, seen = drain(ws, lambda m: m.get("type") == "backchannel")
            assert back["duration_ms"] == 700
            assert any(
                m.get("type") == "vad" and m.get("event") == "speech_discarded"
                for m in seen
            )
            assert not any(m.get("type") == "stop_playback" for m in seen)
            assert not any(is_state("listening")(m) for m in seen)
            ws.send_json({
                "type": "playback_ack", "item_id": speech["item_id"],
                "seq": 0, "played": True,
            })
            drain(ws, is_state("idle"))


def test_barge_in_stops_playback_and_starts_new_turn(factory):
    app, c = factory()
    fake_voice(app)
    with c:
        with c.websocket_connect("/v2/duplex/ws") as ws:
            auth(ws)
            ws.send_json({"type": "text", "text": "你好"})
            first, _ = drain(ws, lambda m: m.get("type") == "speech")
            for _ in range(5):  # 500ms of real speech interrupts playback
                ws.send_bytes(LOUD * 5)
            stop, _ = drain(ws, lambda m: m.get("type") == "stop_playback")
            assert stop["item_id"] == first["item_id"]
            drain(ws, is_state("listening"))  # listening follows stop_playback
            ws.send_bytes(SILENT * 35)
            end, seen = drain(
                ws, lambda m: m.get("type") == "vad" and m.get("event") == "speech_end"
            )
            assert end["voiced_ms"] == 500 and end["duration_ms"] == 1100
            assert not any(m.get("type") == "stop_playback" for m in seen)
            transcript, _ = drain(ws, lambda m: m.get("type") == "transcript")
            assert transcript["text"] == "我喜欢温水"
            second, _ = drain(ws, lambda m: m.get("type") == "speech")
            assert second["item_id"] != first["item_id"]
            ws.send_json({
                "type": "playback_ack", "item_id": second["item_id"],
                "seq": 0, "played": True,
            })
            drain(ws, is_state("idle"))


# ---------- background work: completion is not delivery ----------

def test_delegation_delivers_only_after_playback_ack(factory):
    app, c = factory()
    fake_voice(app)
    app.state.duplex.poll_interval = 0.05
    with c:
        with c.websocket_connect("/v2/duplex/ws") as ws:
            auth(ws)
            ws.send_json({"type": "delegate", "text": "帮我整理一份周报"})
            work_msg, _ = drain(ws, lambda m: m.get("type") == "work")
            work = work_msg["work"]
            assert work["state"] == "QUEUED"
            speech, seen = drain(
                ws, lambda m: m.get("type") == "speech" and m["kind"] == "work"
            )
            assert speech["item_id"] == work["id"]
            assert speech["text"].startswith("你之前让我处理的事有结果了：")
            assert any(is_state("speaking")(m) for m in seen)
            ws.send_json({
                "type": "playback_ack", "item_id": work["id"],
                "seq": 0, "played": True,
            })
            drain(ws, is_state("idle"))
            view = wait_work(c, work["id"], "DELIVERED")
            assert view["delivered_at"]
            assert view["result"]["reply"] == "本地回答"


def test_interrupted_work_is_redelivered(factory):
    app, c = factory()
    fake_voice(app)
    app.state.duplex.poll_interval = 0.05
    with c:
        with c.websocket_connect("/v2/duplex/ws") as ws:
            auth(ws)
            ws.send_json({"type": "delegate", "text": "帮我整理一份周报"})
            work = drain(ws, lambda m: m.get("type") == "work")[0]["work"]
            drain(ws, lambda m: m.get("type") == "speech" and m["kind"] == "work")
            ws.send_json({"type": "interrupt"})
            stop, _ = drain(ws, lambda m: m.get("type") == "stop_playback")
            assert stop["item_id"] == work["id"]
            drain(ws, is_state("idle"))
            speech, _ = drain(
                ws, lambda m: m.get("type") == "speech" and m["kind"] == "work"
            )
            ws.send_json({
                "type": "playback_ack", "item_id": work["id"],
                "seq": 0, "played": True,
            })
            drain(ws, is_state("idle"))
            wait_work(c, work["id"], "DELIVERED")


def test_cancel_completed_work(factory):
    app, c = factory()
    fake_voice(app)
    app.state.duplex.poll_interval = 0.05
    with c:
        with c.websocket_connect("/v2/duplex/ws") as ws:
            auth(ws)
            ws.send_json({"type": "delegate", "text": "帮我整理一份周报"})
            work = drain(ws, lambda m: m.get("type") == "work")[0]["work"]
        # session closed: work completes but cannot be delivered
        wait_work(c, work["id"], "COMPLETED")
        r = c.post(f"/v2/duplex/works/{work['id']}/cancel")
        assert r.status_code == 200
        assert r.json()["state"] == "CANCELLED"
        assert c.post(f"/v2/duplex/works/{work['id']}/cancel").status_code == 409


def test_work_state_recovery_after_restart(factory):
    app1, _ = factory()
    seeds = {
        " queued-task": "QUEUED",
        "running-task": "RUNNING",
        "delivering-task": "DELIVERING",
        "cancelling-task": "CANCELLING",
        "delivered-task": "DELIVERED",
        "completed-task": "COMPLETED",
    }
    with app1.state.db.tx() as s:
        for text, state in seeds.items():
            app1.state.db.add(s, "owner", "duplex_work", {
                "text": text, "state": state, "origin_session": "dx-old",
            })
    app2, c2 = factory()  # same schema; create_app runs recovery
    r = c2.get("/v2/duplex/works")
    assert r.status_code == 200
    views = {v["text"]: v for v in r.json()}
    for text in (" queued-task", "running-task", "cancelling-task"):
        assert views[text]["state"] == "FAILED"
        assert views[text]["error"] == "process_restarted"
    assert views["delivering-task"]["state"] == "COMPLETED"
    assert views["delivered-task"]["state"] == "DELIVERED"
    assert views["completed-task"]["state"] == "COMPLETED"


# ---------- evolution: behavioral contrasts and composition ----------

def _experiment_payload(name, cand_a, cand_b):
    return {
        "name": name,
        "baseline": "baseline",
        "cases": [
            {"input": "案例甲", "required_terms": ["甲要点"]},
            {"input": "案例乙", "required_terms": ["乙要点"]},
            {"input": "案例丙", "required_terms": ["丙要点"]},
        ],
        "candidates": [
            {"name": "baseline", "outputs": ["无关甲", "无关乙", "含丙要点"]},
            {"name": "cand_a", "outputs": cand_a},
            {"name": "cand_b", "outputs": cand_b},
        ],
    }


def test_evolution_contrasts_compose_and_release(factory):
    _, c = factory()
    payload = _experiment_payload(
        "组合建议实验",
        ["含甲要点", "无关乙", "含丙要点"],
        ["无关甲", "含乙要点", "含丙要点"],
    )
    r = post(c, "evolution/experiments", payload, key="exp-compose")
    assert r.status_code == 200
    exp = r.json()
    assert exp["status"] == "evaluated"
    assert exp["runtime_changed"] is False
    assert exp["scoring_immutable"] is True
    scores = {row["name"]: row["score"] for row in exp["results"]}
    assert scores["baseline"] == pytest.approx(1 / 3)
    assert scores["cand_a"] == pytest.approx(2 / 3)
    assert scores["cand_b"] == pytest.approx(2 / 3)
    assert exp["contrasts"]["cand_a"] == {
        "gained": ["案例甲"], "regressed": [],
        "both_pass": ["案例丙"], "both_fail": ["案例乙"],
    }
    assert exp["contrasts"]["cand_b"]["gained"] == ["案例乙"]
    assert exp["contrasts"]["cand_b"]["both_fail"] == ["案例甲"]
    assert exp["compose_suggestion"] == {
        "candidates": ["cand_a", "cand_b"],
        "case_sources": {"cand_a": ["案例甲"], "cand_b": ["案例乙"]},
        "rationale": "disjoint_gains_no_regressions",
    }
    assert exp["winner"] == "cand_a"  # first max wins the tie
    assert exp["recommendation"] == "review_candidate"

    eid = exp["id"]
    assert c.post(
        f"/v2/evolution/experiments/{eid}/approve", json={"candidate": "cand_a"}
    ).status_code == 200
    assert c.post(f"/v2/evolution/experiments/{eid}/release").status_code == 200
    lessons = c.get("/v2/evolution/lessons").json()
    adoption = [l for l in lessons if l["kind"] == "adoption"]
    assert len(adoption) == 1
    assert adoption[0]["evidence"]["gained"] == ["案例甲"]

    assert c.post(f"/v2/evolution/experiments/{eid}/rollback").status_code == 200
    lessons = c.get("/v2/evolution/lessons").json()
    assert len(lessons) == 2
    assert {l["kind"] for l in lessons} == {"adoption", "caution"}

    again = _experiment_payload(
        "后续实验",
        ["含甲要点", "无关乙", "含丙要点"],
        ["无关甲", "含乙要点", "含丙要点"],
    )
    r2 = post(c, "evolution/experiments", again, key="exp-compose-2")
    assert r2.status_code == 200
    assert r2.json()["prior_lessons"]


def test_evolution_regressions_block_composition(factory):
    _, c = factory()
    payload = _experiment_payload(
        "回退守卫实验",
        ["含甲要点", "无关乙", "无关丙"],
        ["无关甲", "含乙要点", "无关丙"],
    )
    r = post(c, "evolution/experiments", payload, key="exp-guard")
    assert r.status_code == 200
    exp = r.json()
    assert exp["contrasts"]["cand_a"]["regressed"] == ["案例丙"]
    assert exp["compose_suggestion"] is None
    assert exp["winner"] == "baseline"
    assert exp["recommendation"] == "keep_baseline"
    r = c.post(
        f"/v2/evolution/experiments/{exp['id']}/approve",
        json={"candidate": "cand_a"},
    )
    assert r.status_code == 409
