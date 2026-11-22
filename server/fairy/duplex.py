"""Full-duplex voice runtime.

Absorbs two ideas from Realtime-Venus' Harness runtime:
  * completion is not delivery — background work is only DELIVERED after the
    originating session actually played the result (playback ack required);
  * short bursts while the assistant speaks are backchannels, real speech
    (>=500ms) is a barge-in that stops playback immediately.

Audio path: client sends PCM16LE mono 16k frames over WebSocket; an energy VAD
segments utterances; local whisper transcribes; the shared turn pipeline
answers; local TTS speaks sentence chunks that the client acknowledges.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import math
import re
import sys
import wave
from array import array
from collections import deque
from uuid import uuid4

from fastapi import HTTPException

from .service import fail
from .store import now, view
from .voice import TranscriptionInput

FRAME_BYTES = 640  # 20ms of PCM16LE mono @16kHz


class EnergyVad:
    """Tiny energy VAD: adaptive noise floor, 40ms onset, 600ms offset."""

    def __init__(self) -> None:
        self.noise_floor = 120.0
        self.in_speech = False
        self.speech_ms = 0
        self.voiced_ms = 0
        self.silence_ms = 0
        self._voiced_run = 0
        self._buf = bytearray()

    def push(self, pcm: bytes) -> list[dict]:
        self._buf.extend(pcm)
        events: list[dict] = []
        while len(self._buf) >= FRAME_BYTES:
            frame = bytes(self._buf[:FRAME_BYTES])
            del self._buf[:FRAME_BYTES]
            samples = array("h", frame)
            if sys.byteorder == "big":
                samples.byteswap()
            rms = int(math.sqrt(sum(s * s for s in samples) / len(samples)))
            threshold = max(250.0, self.noise_floor * 3)
            voiced = rms >= threshold
            if not voiced:
                self.noise_floor = 0.95 * self.noise_floor + 0.05 * rms
            if not self.in_speech:
                self._voiced_run = self._voiced_run + 1 if voiced else 0
                if self._voiced_run >= 2:
                    self.in_speech = True
                    self.speech_ms = 40
                    self.voiced_ms = 40
                    self.silence_ms = 0
                    events.append({"event": "speech_start", "duration_ms": 40})
            else:
                self.speech_ms += 20
                if voiced:
                    self.voiced_ms += 20
                    self.silence_ms = 0
                else:
                    self.silence_ms += 20
                if self.silence_ms >= 600 or self.speech_ms >= 30000:
                    kind = "speech_end" if self.voiced_ms >= 250 else "speech_discarded"
                    events.append({"event": kind, "duration_ms": self.speech_ms, "voiced_ms": self.voiced_ms})
                    self.in_speech = False
                    self.speech_ms = 0
                    self.voiced_ms = 0
                    self.silence_ms = 0
                    self._voiced_run = 0
        return events


def split_sentences(text: str, limit: int = 120) -> list[str]:
    pieces = re.split(r"(?<=[。！？!?；;])|(?<=\.)\s+|\n+", text or "")
    merged: list[str] = []
    for piece in pieces:
        piece = piece.strip()
        if not piece:
            continue
        if merged and len(piece) < 8:
            merged[-1] += piece
        else:
            merged.append(piece)
    out: list[str] = []
    for sentence in merged:
        while len(sentence) > limit:
            out.append(sentence[:limit])
            sentence = sentence[limit:]
        if sentence:
            out.append(sentence)
    return out


def wav_wrap(pcm: bytes, rate: int = 16000) -> bytes:
    if len(pcm) % 2:
        pcm = pcm[:-1]
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


class DuplexSession:
    """One WebSocket conversation: VAD -> ASR -> turn -> chunked TTS playback."""

    def __init__(self, ws, runtime: "DuplexRuntime", session_id: str) -> None:
        self.ws = ws
        self.runtime = runtime
        self.session_id = session_id
        self.state = "idle"
        self.closed = False
        self.vad = EnergyVad()
        self.preroll: deque[bytes] = deque(maxlen=4)
        self.utterance = bytearray()
        self.turn_task: asyncio.Task | None = None
        self.playback: dict | None = None
        self.speech_lock = asyncio.Lock()

    async def send(self, payload: dict) -> None:
        if self.closed:
            return
        try:
            await self.ws.send_json(payload)
        except Exception:
            self.closed = True
            self._stop_playback()

    async def _set_state(self, state: str) -> None:
        self.state = state
        await self.send({"type": "state", "state": state})

    def _stop_playback(self) -> dict | None:
        pb = self.playback
        if pb and not pb["stopped"]:
            pb["stopped"] = True
            pb["done"].set()
            return {"type": "stop_playback", "item_id": pb["item_id"], "playback_id": pb["playback_id"]}
        return None

    async def handle_audio(self, pcm: bytes) -> None:
        if len(pcm) > 65536:
            await self.send({"type": "error", "detail": "audio_chunk_too_large"})
            return
        events = self.vad.push(pcm)
        started = any(e["event"] == "speech_start" for e in events)
        ended = [e for e in events if e["event"] in ("speech_end", "speech_discarded")]
        if started:
            if self.state == "thinking" and self.turn_task and not self.turn_task.done():
                self.turn_task.cancel()
            if self.state in ("idle", "thinking"):
                await self._set_state("listening")
            self.utterance = bytearray(b"".join(self.preroll))
            self.preroll.clear()
        if self.vad.in_speech or started or ended:
            self.utterance.extend(pcm)
        else:
            self.preroll.append(pcm)
        for event in events:
            await self.send({"type": "vad", **event})
        if self.state == "speaking" and (
            (self.vad.in_speech and self.vad.voiced_ms >= 500)
            or any(e["event"] == "speech_end" and e.get("voiced_ms", 0) >= 500 for e in ended)
        ):
            item = self._stop_playback()
            if item:
                await self.send(item)
            await self._set_state("listening")
        for event in ended:
            await self._on_speech_finished(event)

    async def _on_speech_finished(self, event: dict) -> None:
        audio = bytes(self.utterance)
        self.utterance = bytearray()
        if self.state == "speaking":
            # Short burst during playback: backchannel, not a new turn.
            await self.send({"type": "backchannel", "duration_ms": event["duration_ms"]})
            return
        if event["event"] == "speech_discarded":
            await self._set_state("idle")
            return
        self.turn_task = asyncio.create_task(self._process(audio))

    async def _process(self, audio: bytes) -> None:
        await self._set_state("thinking")
        try:
            result = await asyncio.to_thread(
                self.runtime.voice.transcribe,
                TranscriptionInput(
                    audio_base64=base64.b64encode(wav_wrap(audio)).decode(),
                    media_type="audio/wav",
                    language="zh",
                ),
            )
        except HTTPException as exc:
            await self.send({"type": "asr_error", "detail": str(exc.detail)})
            await self._set_state("idle")
            return
        except Exception:
            await self.send({"type": "asr_error", "detail": "local_asr_failed"})
            await self._set_state("idle")
            return
        text = (result.get("text") or "").strip()
        if not text:
            await self._set_state("idle")
            return
        await self.send({"type": "transcript", "text": text})
        self._start_turn(text)

    def _start_turn(self, text: str) -> None:
        current = asyncio.current_task()
        if self.turn_task and self.turn_task is not current and not self.turn_task.done():
            self.turn_task.cancel()
        self.turn_task = asyncio.create_task(self._turn_body(text))

    async def _turn_body(self, text: str) -> None:
        await self._set_state("thinking")
        try:
            async with self.runtime.turn_gate:
                result = await self.runtime.run_turn(text, "duplex-" + uuid4().hex)
        except asyncio.CancelledError:
            raise
        except HTTPException as exc:
            await self.send({"type": "error", "detail": str(exc.detail)})
            await self._set_state("idle")
            return
        except Exception:
            await self.send({"type": "error", "detail": "model_failed"})
            await self._set_state("idle")
            return
        if result.get("error") or result.get("status") == "failed":
            await self.send({"type": "error", "detail": str(result.get("error") or "model_failed")})
            await self._set_state("idle")
            return
        reply = result.get("reply") or ""
        await self.send({"type": "reply", "text": reply, "turn_id": result["id"], "route": result.get("model_route")})
        async with self.speech_lock:
            if self.closed:
                return
            await self._set_state("speaking")
            await self.speak(result["id"], reply, kind="reply")
            if self.state == "speaking":
                await self._set_state("idle")

    async def speak(self, item_id: str, text: str, kind: str) -> str:
        if len(text) > 600:
            text = text[:600] + "完整内容可以在后台任务里查看。"
        chunks = split_sentences(text)
        pb = {
            "item_id": item_id,
            "playback_id": uuid4().hex,
            "kind": kind,
            "total": len(chunks),
            "played": set(),
            "stopped": False,
            "done": asyncio.Event(),
        }
        self.playback = pb
        try:
            if not chunks:
                pb["done"].set()
            for seq, chunk in enumerate(chunks):
                if pb["stopped"]:
                    break
                try:
                    audio = await asyncio.to_thread(self.runtime.voice.speak, chunk)
                    audio_b64 = base64.b64encode(audio).decode()
                except Exception:
                    audio_b64 = None  # text-only fallback keeps non-mac hosts usable
                if pb["stopped"]:
                    break
                await self.send({
                    "type": "speech", "item_id": item_id, "playback_id": pb["playback_id"], "kind": kind,
                    "seq": seq, "total": len(chunks), "text": chunk,
                    "audio_base64": audio_b64, "sample_rate": 22050,
                    "final": seq == len(chunks) - 1,
                })
            if not pb["stopped"]:
                try:
                    await asyncio.wait_for(pb["done"].wait(), timeout=180)
                except asyncio.TimeoutError:
                    pb["stopped"] = True
            return "interrupted" if pb["stopped"] else "played"
        finally:
            if self.playback is pb:
                self.playback = None

    def ack(self, item_id: str, seq: int, played: bool, playback_id: str | None = None) -> None:
        pb = self.playback
        if not pb or pb["item_id"] != item_id:
            return
        if playback_id is not None and playback_id != pb["playback_id"]:
            return
        if type(played) is not bool or type(seq) is not int or not 0 <= seq < pb["total"]:
            return
        if not played:
            pb["stopped"] = True
            pb["done"].set()
            return
        pb["played"].add(seq)
        if len(pb["played"]) >= pb["total"]:
            pb["done"].set()

    async def interrupt(self) -> None:
        item = self._stop_playback()
        if item:
            await self.send(item)
        if self.turn_task and not self.turn_task.done():
            self.turn_task.cancel()
        await self._set_state("idle")

    async def handle_json(self, msg: dict) -> None:
        kind = msg.get("type")
        if kind == "text":
            text = str(msg.get("text") or "").strip()[:16000]
            if not text:
                await self.send({"type": "error", "detail": "empty_text"})
                return
            if self.state == "speaking":
                item = self._stop_playback()
                if item:
                    await self.send(item)
            self._start_turn(text)
        elif kind == "interrupt":
            await self.interrupt()
        elif kind == "playback_ack":
            self.ack(msg.get("item_id"), msg.get("seq"), msg.get("played"), msg.get("playback_id"))
        elif kind == "delegate":
            text = str(msg.get("text") or "").strip()[:16000]
            if not text:
                await self.send({"type": "error", "detail": "empty_text"})
                return
            work = self.runtime.delegate(text, self.session_id)
            await self.send({"type": "work", "work": work})
        elif kind == "ping":
            await self.send({"type": "pong"})
        else:
            await self.send({"type": "error", "detail": "unknown_message_type"})

    def can_deliver(self) -> bool:
        return (
            not self.closed
            and self.state == "idle"
            and self.playback is None
            and not self.speech_lock.locked()
            and (self.turn_task is None or self.turn_task.done())
            and not self.vad.in_speech
        )

    def close(self) -> None:
        self.closed = True
        if self.turn_task and not self.turn_task.done():
            self.turn_task.cancel()
        self._stop_playback()
        self.runtime.sessions.discard(self)


class DuplexRuntime:
    """Background work lifecycle: QUEUED -> RUNNING -> COMPLETED -> DELIVERING -> DELIVERED.

    COMPLETED only means the answer exists; DELIVERED requires playback
    acknowledgments. An active originating session gets the result when idle.
    """

    def __init__(self, db, service, run_turn, voice) -> None:
        self.db = db
        self.service = service
        self.run_turn = run_turn
        self.voice = voice
        self.works: dict[str, asyncio.Task] = {}
        self.sessions: set[DuplexSession] = set()
        self.turn_gate = asyncio.Lock()
        self.poll_interval = 0.5
        self._recover()

    def _recover(self) -> None:
        with self.db.tx() as s:
            for row in self.service.rows(s, "duplex_work"):
                data = json.loads(row.payload)
                state = data.get("state")
                if state == "DELIVERING":
                    data["state"] = "COMPLETED"
                elif state in ("QUEUED", "RUNNING", "CANCELLING"):
                    data["state"] = "FAILED"
                    data["error"] = "process_restarted"
                else:
                    continue
                row.payload = json.dumps(data, ensure_ascii=False)
                row.revision += 1
                self.db.emit(s, row.scope, "duplex.work_state", {"id": row.id, "state": data["state"]})

    def _set_work_state(self, work_id: str, state: str, expect: str | None = None, **extra) -> dict:
        with self.db.tx() as s:
            row = self.service.get(s, work_id, "duplex_work")
            data = json.loads(row.payload)
            if expect is not None and data.get("state") != expect:
                fail(409, "work_state_conflict")
            data["state"] = state
            data.update(extra)
            row.payload = json.dumps(data, ensure_ascii=False)
            row.revision += 1
            self.db.emit(s, row.scope, "duplex.work_state", {"id": work_id, "state": state})
            return view(row)

    def _work_view(self, work_id: str) -> dict:
        with self.db.sessions() as s:
            return view(self.service.get(s, work_id, "duplex_work"))

    def delegate(self, text: str, session_id: str) -> dict:
        with self.db.tx() as s:
            row = self.db.add(s, "owner", "duplex_work", {
                "text": text, "state": "QUEUED", "origin_session": session_id,
            })
            self.db.emit(s, "owner", "duplex.work_created", {"id": row.id})
            work = view(row)
        self.works[row.id] = asyncio.create_task(self._work(row.id, text))
        return work

    async def _work(self, work_id: str, text: str) -> None:
        try:
            self._set_work_state(work_id, "RUNNING", expect="QUEUED")
            loop = asyncio.get_running_loop()
            deadline = loop.time() + 120
            while True:
                try:
                    async with self.turn_gate:
                        result = await self.run_turn(text, "duplex-work-" + work_id)
                    break
                except HTTPException as exc:
                    busy = exc.status_code == 409 and str(exc.detail) == "scope_has_pending_turn"
                    if busy and loop.time() < deadline:
                        await asyncio.sleep(1)
                        continue
                    self._set_work_state(work_id, "FAILED", error="busy_timeout" if busy else str(exc.detail))
                    return
                except Exception:
                    self._set_work_state(work_id, "FAILED", error="model_failed")
                    return
            if result.get("error") or result.get("status") == "failed":
                self._set_work_state(work_id, "FAILED", error=str(result.get("error") or "model_failed"))
                return
            self._set_work_state(work_id, "COMPLETED", result={
                "reply": result.get("reply") or "",
                "turn_id": result["id"],
            }, completed_at=now())
            await self._deliver(work_id)
        except asyncio.CancelledError:
            self._cancel_cleanup(work_id)
        finally:
            self.works.pop(work_id, None)

    def _cancel_cleanup(self, work_id: str) -> None:
        try:
            data = self._work_view(work_id)
            if data.get("state") in ("DELIVERED", "FAILED", "CANCELLED"):
                return
            self._set_work_state(work_id, "CANCELLED", cancelled_at=now())
        except Exception:
            pass

    async def _deliver(self, work_id: str) -> None:
        while True:
            data = self._work_view(work_id)
            if data.get("state") != "COMPLETED":
                return
            origin = next(
                (s for s in self.sessions if s.session_id == data.get("origin_session") and not s.closed),
                None,
            )
            session = origin or next((s for s in self.sessions if s.can_deliver()), None)
            if session is None or not session.can_deliver():
                await asyncio.sleep(self.poll_interval)
                continue
            try:
                self._set_work_state(work_id, "DELIVERING", expect="COMPLETED", delivering_to=session.session_id)
            except HTTPException:
                continue
            async with session.speech_lock:
                if (
                    session.closed or session.state != "idle" or session.playback is not None
                    or session.vad.in_speech
                    or (session.turn_task is not None and not session.turn_task.done())
                ):
                    try:
                        self._set_work_state(work_id, "COMPLETED", expect="DELIVERING")
                    except HTTPException:
                        return
                    await asyncio.sleep(self.poll_interval)
                    continue
                await session._set_state("speaking")
                reply = (data.get("result") or {}).get("reply") or ""
                outcome = await session.speak(work_id, "你之前让我处理的事有结果了：" + reply, kind="work")
                if session.state == "speaking":
                    await session._set_state("idle")
            if outcome == "played":
                try:
                    self._set_work_state(work_id, "DELIVERED", expect="DELIVERING", delivered_at=now())
                except HTTPException:
                    pass
                return
            try:
                self._set_work_state(work_id, "COMPLETED", expect="DELIVERING")
            except HTTPException:
                return
            await asyncio.sleep(self.poll_interval)

    def adopt_completed(self, session: DuplexSession) -> None:
        for work in self.service.list("duplex_work"):
            if work.get("state") == "COMPLETED" and work["id"] not in self.works:
                self.works[work["id"]] = asyncio.create_task(self._deliver_guarded(work["id"]))

    async def _deliver_guarded(self, work_id: str) -> None:
        try:
            await self._deliver(work_id)
        except asyncio.CancelledError:
            self._cancel_cleanup(work_id)
        finally:
            self.works.pop(work_id, None)

    async def cancel_work(self, work_id: str) -> dict:
        data = self._work_view(work_id)
        state = data.get("state")
        if state in ("DELIVERED", "CANCELLED", "FAILED"):
            fail(409, "work_not_cancellable")
        if state == "DELIVERING":
            target = data.get("delivering_to")
            for session in self.sessions:
                if session.session_id == target:
                    item = session._stop_playback()
                    if item:
                        await session.send(item)
        task = self.works.get(work_id)
        if task and not task.done():
            self._set_work_state(work_id, "CANCELLING", expect=state)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
            if self._work_view(work_id).get("state") == "CANCELLING":
                self._set_work_state(work_id, "CANCELLED", cancelled_at=now())
        else:
            self._set_work_state(work_id, "CANCELLED", expect=state, cancelled_at=now())
        return self._work_view(work_id)

    def status(self) -> dict:
        counts: dict[str, int] = {}
        for work in self.service.list("duplex_work"):
            state = work.get("state") or "UNKNOWN"
            counts[state] = counts.get(state, 0) + 1
        return {
            "active_sessions": len(self.sessions),
            "works": counts,
            "voice": self.voice.status(),
            "full_duplex": True,
            "barge_in": "energy_vad_500ms",
            "backchannel": "short_burst_ignored",
        }
