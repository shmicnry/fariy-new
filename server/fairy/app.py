from __future__ import annotations
import asyncio
import json
import os
import secrets
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, Depends, Header, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ConfigDict, field_validator
from sqlalchemy import select
from .store import Store, Event, now, view
from .service import fail
from .memories import MemoryService
from .model_settings import ModelSettings, ModelConfig
from .models import ModelRouter
from .learning import LearningService
from .knowledge import KnowledgeService
from .assessments import AssessmentService, QuizInput, RunInput
from .link_fetch import fetch_text, validate_url
from .mac_bridge import MacBridge
from .skills import SkillGrantInput, SkillInvokeInput, SkillService
from .autonomy import AutonomyService
from .evolution import EvolutionService, ExperimentInput
from .worker import read_status
from .voice import SpeechInput, TranscriptionInput, VoiceService
from .semantic import SemanticService
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Text(Strict):
    text: str = Field(min_length=1, max_length=16000)


class TurnInput(Text):
    routing: Literal["auto", "local_only", "cloud_assist"] = "auto"


class MemoryProposal(Text):
    source_id: str = Field(min_length=1, max_length=100)


class MemoryReview(Strict):
    revision: int = Field(ge=1)
    decision: Literal["approve", "reject"]
    subject: Literal["owner", "assistant", "other", "unspecified"] | None = None


class MemoryCorrection(Text):
    subject: Literal["owner", "assistant", "other", "unspecified"] | None = None
    revision: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=1000)


class Memory(Text):
    source_ids: list[str] = Field(min_length=1, max_length=8)


class Material(Text):
    title: str = Field(min_length=1, max_length=160)


class FileMaterial(Strict):
    filename: str = Field(min_length=1, max_length=160)
    content_base64: str = Field(min_length=1, max_length=1400000)


class Practice(Strict):
    revision: int = Field(ge=1)
    answer: str = Field(min_length=1, max_length=8000)
    evidence: str = Field(min_length=1, max_length=4000)


class LinkInput(Strict):
    url: str = Field(min_length=1, max_length=2000)
    title: str = Field(min_length=1, max_length=160)


class SourceReview(Strict):
    revision: int = Field(ge=1)
    rating: Literal["unreviewed", "primary", "corroborated", "disputed", "rejected"]
    reason: str = Field(min_length=1, max_length=2000)
    expires_at: str | None = None


class SourceRefresh(Strict):
    revision: int = Field(ge=1)


class WorldClaim(Strict):
    subject: str = Field(min_length=1, max_length=160)
    predicate: str = Field(min_length=1, max_length=160)
    value: str = Field(min_length=1, max_length=2000)
    source_id: str = Field(min_length=1, max_length=100)
    quote: str = Field(min_length=1, max_length=4000)


class PracticeGrade(Strict):
    revision: int = Field(ge=1)
    score: int = Field(ge=0, le=5, strict=True)
    feedback: str = Field(min_length=1, max_length=2000)


class Card(Text):
    title: str = Field(min_length=1, max_length=160)
    subtype: Literal["note", "todo", "reminder", "anniversary"] = "note"
    remind_at: str | None = None


class Assessment(Strict):
    revision: int = Field(ge=1)
    passed: bool
    evidence: str = Field(min_length=1, max_length=4000)


class Config(Strict):
    revision: int = Field(ge=0)
    daily_minutes: int = Field(default=45, ge=0, le=240)
    pet_enabled: bool = False
    mac_execute: bool = False
    autonomous_paid: bool = False
    mac_allowed_apps: list[str] = Field(default_factory=list, max_length=16)
    mac_allowed_paths: list[str] = Field(default_factory=list, max_length=16)
    autonomy_enabled: bool = False
    autonomy_daily_minutes: int = Field(default=30, ge=0, le=240)
    autonomy_daily_items: int = Field(default=10, ge=0, le=100)
    source_refresh_enabled: bool = False
    source_refresh_interval_hours: int = Field(default=24, ge=1, le=168)
    source_refresh_daily_limit: int = Field(default=5, ge=0, le=50)

    @field_validator("mac_allowed_apps")
    @classmethod
    def valid_app_allowlist(cls, value):
        cleaned = []
        for item in value:
            item = item.strip()
            if (
                not item
                or len(item) > 500
                or any(ord(character) < 32 or ord(character) == 127 for character in item)
            ):
                raise ValueError("invalid_allowed_application")
            if item not in cleaned:
                cleaned.append(item)
        return cleaned

    @field_validator("mac_allowed_paths")
    @classmethod
    def valid_path_allowlist(cls, value):
        cleaned = []
        for item in value:
            item = item.strip()
            if (
                not item
                or len(item) > 2000
                or any(ord(character) < 32 or ord(character) == 127 for character in item)
                or not Path(item).is_absolute()
            ):
                raise ValueError("allowed_paths_must_be_absolute")
            if item not in cleaned:
                cleaned.append(item)
        return cleaned


class CandidateChoice(Strict):
    revision: int = Field(ge=1)


class GoalCompletion(CandidateChoice):
    summary: str = Field(min_length=1, max_length=8000)


class EvolutionApproval(Strict):
    candidate: str = Field(min_length=1, max_length=80)


class Choice(Strict):
    revision: int = Field(ge=1)
    action_digest: str
    choice: Literal["allow_once", "reject"]


def create_app(url=None, token=None, transport=None, secrets_dir=None):
    Path("var").mkdir(exist_ok=True)
    database_url = url or os.getenv("FAIRY_DATABASE_URL")
    if not database_url:
        raise RuntimeError("database_url_required")
    db = Store(database_url)
    service = MemoryService(db)
    model_settings = ModelSettings(db, secrets_dir=secrets_dir)
    router = ModelRouter(service, model_settings, transport=transport)
    semantic = SemanticService(db, model_settings, transport=transport)
    skill_service = SkillService(db)
    skill_service.semantic = semantic
    mac_bridge = MacBridge(service)
    autonomy = AutonomyService(db)
    evolution = EvolutionService(db)
    voice = VoiceService()
    app = FastAPI(title="Fairy Core", version="0.3.0")
    app.state.db = db
    app.state.service = service
    app.state.model_settings = model_settings
    app.state.router = router
    app.state.skills = skill_service
    app.state.mac_bridge = mac_bridge
    app.state.autonomy = autonomy
    app.state.evolution = evolution
    app.state.voice = voice
    app.state.semantic = semantic
    app.state.worker_state_dir = os.getenv("FAIRY_STATE_DIR", "var")

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Validation errors must never echo write-only provider credentials.
        return JSONResponse(
            {
                "detail": [
                    {"loc": e["loc"], "type": e["type"], "msg": e["msg"]}
                    for e in exc.errors()
                ]
            },
            status_code=422,
        )

    @app.middleware("http")
    async def local_boundary(request, call_next):
        from urllib.parse import urlsplit
        from fastapi.responses import JSONResponse

        host = request.url.hostname
        trusted_hosts = {"127.0.0.1", "localhost", "::1", "testserver"}
        if os.getenv("FAIRY_ALLOW_LAN") == "1":
            trusted_hosts.update(
                item.strip().casefold()
                for item in os.getenv("FAIRY_ALLOWED_HOSTS", "").split(",")
                if item.strip()
            )
        if (host or "").casefold() not in trusted_hosts:
            return JSONResponse({"detail": "loopback_host_required"}, status_code=421)
        origin = request.headers.get("origin")
        if origin:
            parsed = urlsplit(origin)
            if (
                parsed.hostname != host
                or parsed.port != request.url.port
                or parsed.scheme != request.url.scheme
            ):
                return JSONResponse({"detail": "same_origin_required"}, status_code=403)
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    secret = token if token is not None else os.getenv("FAIRY_TOKEN", "")

    async def auth(authorization: str = Header(default="")):
        if not secret:
            fail(503, "server_token_not_configured")
        if not secrets.compare_digest(
            authorization.encode(), ("Bearer " + secret).encode()
        ):
            fail(401, "unauthorized")
        return "owner"

    async def key(idempotency_key: str = Header(min_length=1, max_length=128)):
        return idempotency_key

    api = FastAPI(dependencies=[Depends(auth)])
    api.add_exception_handler(RequestValidationError, validation_error)

    @app.get("/healthz")
    def health():
        return {"status": "ok", "version": "0.3.0", "runtime": "development"}

    @api.get("/capabilities")
    def capabilities():
        with db.sessions() as session:
            configured = [
                row for row in service.rows(session, "config") if row.status == "active"
            ]
            config = json.loads(configured[0].payload) if configured else {}
        return {
            "scope": "owner",
            "principal": "confirmed_by_token",
            "storage": db.engine.dialect.name,
            "text_model": bool(model_settings.runtime()["ollama_model"]),
            "primary_provider": "ollama",
            "cloud_fallback_configured": model_settings.public()["cloud_ready"],
            "reviewed_memory": True,
            "memory_corrections": True,
            "text_materials": True,
            "document_formats": [
                ".txt",
                ".md",
                ".pdf",
                ".docx",
                ".png",
                ".jpg",
                ".jpeg",
                ".heic",
                ".tiff",
            ],
            "source_review": True,
            "source_version_refresh": True,
            "scheduled_source_refresh": True,
            "world_claims": True,
            "fixed_choice_assessments": True,
            "skills_registry": True,
            "mac_read_only": True,
            "mac_ax_tree_read_only": True,
            "autonomy_queue": True,
            "autonomy_goal_ledger": True,
            "evolution_lab": True,
            "worker_status_endpoint": True,
            "cross_page_event_sync": True,
            "local_notification_center": True,
            "local_tts": voice.status()["local_tts"],
            "local_asr": voice.status()["local_asr"],
            "semantic_model_embeddings": semantic.configuration()["enabled"],
            "mac_execute": bool(config.get("mac_execute")),
            "mac_execute_scope": (
                "allowlisted_app_launch" if config.get("mac_execute") else "disabled"
            ),
            "video": False,
            "automatic_mastery": False,
            "vector_search": True,
            "vector_search_mode": "local_character_vector_hybrid",
            "semantic_model": semantic.configuration()["model"],
            "wardrobe_rendering": False,
        }

    @api.get("/models/config")
    def get_models():
        return model_settings.public()

    @api.put("/models/config")
    def set_models(body: ModelConfig):
        return model_settings.save(body)

    @api.get("/models/ollama")
    async def local_models():
        return await router.installed()

    @api.get("/semantic/status")
    def semantic_status():
        return semantic.configuration()

    @api.get("/models/invocations")
    def invocations(limit: int = Query(default=100, ge=1, le=1000)):
        return service.list("model_invocation")[-limit:]

    @api.post("/turns")
    async def turn(body: TurnInput, k=Depends(key)):
        r = service.start_turn(body.text, k, body.routing)
        if r.pop("_replayed", False) or r["status"] != "pending":
            with db.sessions() as s:
                return view(service.get(s, r["id"]))
        context, snapshot = service.model_context(body.text)
        try:
            result = await router.answer(r, body.text, body.routing, context, snapshot)
        except asyncio.CancelledError:
            service.finish_turn(r["id"], error="request_cancelled", snapshot=snapshot)
            raise
        except Exception:
            # No provider text or credentials in errors. Dispatch reservations remain durable.
            return service.finish_turn(r["id"], error="model_failed", snapshot=snapshot)
        return service.finish_turn(
            r["id"],
            text=result.reply,
            error=result.error,
            snapshot=snapshot,
            metadata=result.route,
            proposals=result.proposals,
        )

    @api.get("/turns")
    def turns():
        return service.list("turn")

    @api.post("/turns/{id}/cancel")
    def cancel(id: str):
        return service.cancel(id)

    @api.get("/memories")
    def memories(q: str = Query(default="", max_length=1000)):
        return service.recall(q) if q else service.list("memory")

    @api.post("/memories")
    def memory(body: Memory, k=Depends(key)):
        return service.memory(body.text, body.source_ids, k)

    @api.get("/memory/proposals")
    def memory_proposals():
        return service.list("memory_proposal")

    @api.post("/memory/proposals")
    def memory_proposal(body: MemoryProposal, k=Depends(key)):
        return service.propose(body.text, body.source_id, k)

    @api.post("/memory/proposals/{id}/review")
    def review_memory(id: str, body: MemoryReview, k=Depends(key)):
        return service.review(id, body.revision, body.decision, k, subject=body.subject)

    @api.patch("/memories/{id}")
    def correct_memory(id: str, body: MemoryCorrection, k=Depends(key)):
        return service.correct(
            id, body.revision, body.text, body.reason, k, subject=body.subject
        )

    @api.get("/memories/{id}/history")
    def memory_history(id: str):
        return service.history(id)

    @api.get("/sources/{id}")
    def original_source(id: str):
        with db.sessions() as s:
            r = service.get(s, id)
            if r.kind not in ("evidence", "material") or r.status != "active":
                fail(404, "source_not_available")
            return view(r)

    @api.delete("/memories/{id}")
    def forget_memory(id: str, revision: int = Query(ge=1)):
        with db.sessions() as s:
            service.get(s, id, "memory")
        return service.invalidate(id, revision)

    @api.delete("/records/{id}")
    def delete(id: str, revision: int = Query(ge=1)):
        return service.invalidate(id, revision)

    @api.post("/learning/links")
    async def import_link(body: LinkInput, k=Depends(key)):
        try:
            validate_url(body.url)
        except ValueError:
            fail(422, "public_https_url_required")
        return await asyncio.to_thread(
            KnowledgeService(db).link, body.url, body.title, k, fetch_text
        )

    @api.get("/learning/links")
    def links():
        return service.list("link_import")

    @api.get("/learning/sources")
    def sources():
        with db.sessions() as s:
            schedules = {
                json.loads(row.payload).get("source_id"): view(row)
                for row in service.rows(s, "source_refresh_schedule")
                if row.status == "active"
            }
            results = []
            for row in service.list("material"):
                source = service.get(s, row["id"], "material")
                row["source_eligible"] = service.source_eligible(source)
                row["refresh_schedule"] = schedules.get(row["id"])
                results.append(row)
            return results

    @api.patch("/learning/sources/{id}")
    def source_review(id: str, body: SourceReview):
        return KnowledgeService(db).source_review(
            id, body.revision, body.rating, body.reason, body.expires_at
        )

    @api.post("/learning/sources/{id}/refresh")
    async def source_refresh(id: str, body: SourceRefresh, k=Depends(key)):
        return await asyncio.to_thread(
            KnowledgeService(db).refresh_source,
            id,
            body.revision,
            k,
            fetch_text,
        )

    @api.post("/world/claims")
    def claim(body: WorldClaim, k=Depends(key)):
        return KnowledgeService(db).claim(
            body.subject, body.predicate, body.value, body.source_id, body.quote, k
        )

    @api.get("/world/claims")
    def world():
        return KnowledgeService(db).world()

    @api.patch("/learning/practice/{id}")
    def grade(id: str, body: PracticeGrade):
        return KnowledgeService(db).grade(id, body.revision, body.score, body.feedback)

    @api.post("/learning/quizzes")
    def create_quiz(body: QuizInput, k=Depends(key)):
        return AssessmentService(db).quiz(body, k)

    @api.get("/learning/quizzes")
    def quizzes():
        with db.sessions() as s:
            results = []
            for row in service.list("quiz"):
                quiz = service.get(s, row["id"], "quiz")
                data = json.loads(quiz.payload)
                row["source_eligible"] = all(
                    service.source_eligible(service.get(s, source_id))
                    for source_id in data["source_ids"]
                )
                results.append(row)
            return results

    @api.post("/learning/quizzes/{id}/runs")
    async def run_quiz(id: str, body: RunInput, k=Depends(key)):
        return await AssessmentService(db).run(id, body.mode, k, router)

    @api.get("/learning/assessment-runs")
    def assessment_runs():
        with db.sessions() as s:
            results = []
            for row in service.list("assessment_attempt"):
                record = service.get(s, row["id"], "assessment_attempt")
                data = json.loads(record.payload)
                refs = [
                    service.get(s, source_id)
                    for source_id in data.get("source_ids", [])
                ]
                row["source_eligible"] = all(
                    service.source_eligible(ref) for ref in refs
                )
                results.append(row)
            return results

    @api.post("/learning/assessment-runs/{id}/cancel")
    def stop_assessment(id: str):
        with db.tx() as s:
            r = service.get(s, id, "assessment_attempt")
            if r.status == "pending":
                r.status = "interrupted"
                r.revision += 1
                for invocation in service.rows(s, "model_invocation"):
                    data = json.loads(invocation.payload)
                    if data.get("turn_id") == id and invocation.status == "started":
                        invocation.status = "unknown"
                        invocation.revision += 1
                        data.update(
                            error="request_cancelled",
                            finished_at=now(),
                        )
                        invocation.payload = json.dumps(data)
            return view(r)

    @api.post("/learning/materials")
    def material(body: Material, k=Depends(key)):
        return service.material(body.title, body.text, k)

    @api.post("/learning/files")
    def file_material(body: FileMaterial, k=Depends(key)):
        return LearningService(db).ingest(body.filename, body.content_base64, k)

    @api.get("/learning/courses/{id}/chunks")
    def course_chunks(id: str):
        with db.sessions() as s:
            service.get(s, id, "course")
        return sorted(
            [r for r in service.list("learning_chunk") if r["course_id"] == id],
            key=lambda r: r["index"],
        )

    @api.post("/learning/courses/{id}/practice")
    def practice(id: str, body: Practice, k=Depends(key)):
        return LearningService(db).practice(
            id, body.revision, body.answer, body.evidence, k
        )

    @api.get("/learning/courses/{id}/practice")
    def practices(id: str):
        with db.sessions() as s:
            service.get(s, id, "course")
        return [r for r in service.list("practice") if r["course_id"] == id]

    @api.get("/learning/search")
    async def search_learning(q: str = Query(min_length=1, max_length=1000)):
        from .cognition import relevance

        candidates = []
        with db.sessions() as s:
            for row in service.rows(s, "learning_chunk"):
                if row.status != "active":
                    continue
                d = json.loads(row.payload)
                if any(
                    not service.source_eligible(service.get(s, id))
                    for id in d["source_ids"]
                ):
                    continue
                score = relevance(q, d["text"])
                candidates.append(dict(view(row), lexical_relevance=score))
        reranked = await semantic.rerank(
            q,
            [
                {"id": item["id"], "text": item["text"]}
                for item in candidates[:200]
            ],
        )
        if reranked is None:
            results = [
                dict(item, relevance=item["lexical_relevance"])
                for item in candidates
                if item["lexical_relevance"] > 0
            ]
            return {
                "results": sorted(
                    results, key=lambda r: (-r["relevance"], r["id"])
                )[:20],
                "retrieval_mode": "local_character_vector_hybrid_chunks",
                "semantic_available": False,
            }
        semantic_by_id = {
            item["id"]: item["semantic_relevance"] for item in reranked
        }
        results = []
        for item in candidates:
            if item["id"] not in semantic_by_id:
                continue
            item["semantic_relevance"] = semantic_by_id[item["id"]]
            item["relevance"] = round(
                item["lexical_relevance"] * 0.55
                + max(0.0, item["semantic_relevance"] - 0.35) * 0.45,
                6,
            )
            if item["lexical_relevance"] > 0 or item["semantic_relevance"] >= 0.68:
                results.append(item)
        return {
            "results": sorted(results, key=lambda r: (-r["relevance"], r["id"]))[:20],
            "retrieval_mode": "ollama_semantic_rerank_with_local_character_fallback",
            "semantic_available": True,
        }

    @api.get("/learning/courses/{id}/effect")
    def learning_effect(id: str):
        with db.sessions() as s:
            course = service.get(s, id, "course")
        course_sources = set(json.loads(course.payload).get("source_ids", []))
        with db.sessions() as s:
            course_source_eligible = all(
                service.source_eligible(service.get(s, source_id))
                for source_id in course_sources
            )
        all_rows = [r for r in service.list("practice") if r["course_id"] == id]
        graded = sorted(
            [r for r in all_rows if r["evaluation"] != "ungraded"],
            key=lambda r: r["reviewed_at"],
        )
        assessment_attempts = []
        invalidated_assessment_attempts = 0
        with db.sessions() as s:
            for attempt in service.list("assessment_attempt"):
                if attempt.get("status") != "completed" or not course_sources & set(
                    attempt.get("source_ids", [])
                ):
                    continue
                refs = [
                    service.get(s, source_id)
                    for source_id in attempt.get("source_ids", [])
                ]
                if all(service.source_eligible(ref) for ref in refs):
                    assessment_attempts.append(attempt)
                else:
                    invalidated_assessment_attempts += 1
        return {
            "attempts": len(all_rows),
            "reviewed_attempts": len(graded),
            "source_eligible": course_source_eligible,
            "latest_score": (
                graded[-1]["score"] if graded and course_source_eligible else None
            ),
            "historical_latest_score": graded[-1]["score"] if graded else None,
            "initial_score": (
                graded[0]["score"] if graded and course_source_eligible else None
            ),
            "score_change": (
                graded[-1]["score"] - graded[0]["score"]
                if graded and course_source_eligible
                else None
            ),
            "model_assessment_runs": len(assessment_attempts),
            "invalidated_model_assessment_runs": invalidated_assessment_attempts,
            "model_assessment_latest": (
                {
                    "correct_count": assessment_attempts[-1]["correct_count"],
                    "total": assessment_attempts[-1]["total"],
                    "mode": assessment_attempts[-1]["mode"],
                }
                if assessment_attempts
                else None
            ),
            "method": "owner_rubric",
            "generalization_verified": False,
        }

    @api.get("/learning/courses")
    def courses():
        with db.sessions() as s:
            results = []
            for row in service.list("course"):
                course = service.get(s, row["id"], "course")
                data = json.loads(course.payload)
                row["source_eligible"] = all(
                    service.source_eligible(service.get(s, source_id))
                    for source_id in data["source_ids"]
                )
                results.append(row)
            return results

    @api.post("/learning/courses/{id}/assess")
    def assess(id: str, body: Assessment):
        return service.assess(id, body.revision, body.passed, body.evidence)

    @api.post("/skills/acquired")
    def acquire(course_id: str, k=Depends(key)):
        return service.acquire(course_id, k)

    @api.get("/skills")
    def skills():
        return service.list("acquired_skill")

    @api.post("/cards")
    def card(body: Card, k=Depends(key)):
        return service.custom_card(
            body.title, body.text, body.subtype, body.remind_at, k
        )

    @api.get("/cards")
    def cards():
        return service.list("card")

    @api.post("/approvals")
    def propose(body: Material, k=Depends(key)):
        return service.propose_note(body.title, body.text, k)

    @api.get("/approvals")
    def approvals():
        return service.list("approval")

    @api.post("/approvals/{id}/choices")
    def choose(id: str, body: Choice, k=Depends(key)):
        return service.choose_note(
            id, body.revision, body.action_digest, body.choice, k
        )

    @api.get("/notes")
    def notes():
        return service.list("note")

    @api.get("/config")
    def config():
        return service.list("config")

    @api.put("/config")
    def set_config(body: Config):
        data = body.model_dump(exclude={"revision"})
        autonomy.validate_config(data)
        return service.configure(body.revision, data)

    @api.get("/jobs")
    def jobs():
        return service.list("job")

    @api.get("/worker/status")
    def worker_status():
        return read_status(app.state.worker_state_dir) or {
            "status": "missing",
            "alive": False,
        }

    @api.get("/voice/status")
    def voice_status():
        return voice.status()

    @api.post("/voice/speak")
    def voice_speak(body: SpeechInput):
        from fastapi import Response

        return Response(
            content=voice.speak(body.text),
            media_type="audio/wav",
            headers={"Cache-Control": "no-store"},
        )

    @api.post("/voice/transcribe")
    def voice_transcribe(body: TranscriptionInput):
        return voice.transcribe(body)

    @api.get("/mac/status")
    def mac_status():
        return mac_bridge.status()

    @api.get("/mac/apps")
    def mac_apps():
        return mac_bridge.applications()

    @api.get("/mac/files")
    def mac_files(path: str = Query(min_length=1, max_length=2000)):
        return mac_bridge.files(path)

    @api.get("/skills/registry")
    def skill_registry():
        return skill_service.list("skill_package")

    @api.post("/skills/registry/{id}/install")
    def install_skill(id: str):
        return skill_service.install(id)

    @api.post("/skills/registry/{id}/grant")
    def grant_skill(id: str, body: SkillGrantInput):
        return skill_service.grant(id, body)

    @api.post("/skills/registry/{id}/disable")
    def disable_skill(id: str):
        return skill_service.disable(id)

    @api.post("/skills/registry/{id}/invoke")
    async def invoke_skill(id: str, body: SkillInvokeInput):
        return await skill_service.invoke(id, body)

    @api.get("/autonomy/budget")
    def autonomy_budget():
        return autonomy.budget()

    @api.get("/autonomy/goals")
    def autonomy_goals():
        return autonomy.goals()

    @api.post("/autonomy/goals/{id}/start")
    def start_autonomy_goal(id: str, body: CandidateChoice):
        return autonomy.start(id, body.revision)

    @api.post("/autonomy/goals/{id}/pause")
    def pause_autonomy_goal(id: str, body: CandidateChoice):
        return autonomy.pause(id, body.revision)

    @api.post("/autonomy/goals/{id}/complete")
    def complete_autonomy_goal(id: str, body: GoalCompletion):
        return autonomy.complete(id, body.revision, body.summary)

    @api.post("/autonomy/goals/{id}/cancel")
    def cancel_autonomy_goal(id: str, body: CandidateChoice):
        return autonomy.cancel(id, body.revision)

    @api.get("/autonomy/candidates")
    def autonomy_candidates():
        return autonomy.list("autonomy_candidate")

    @api.post("/autonomy/refresh")
    def refresh_autonomy():
        autonomy.enforce_budget()
        return autonomy.refresh()

    @api.post("/autonomy/candidates/{id}/accept")
    def accept_candidate(id: str, body: CandidateChoice):
        return autonomy.accept(id, body.revision)

    @api.post("/autonomy/candidates/{id}/dismiss")
    def dismiss_candidate(id: str, body: CandidateChoice):
        return autonomy.dismiss(id, body.revision)

    @api.get("/evolution/experiments")
    def experiments():
        return evolution.list("evolution_experiment")

    @api.post("/evolution/experiments")
    def create_experiment(body: ExperimentInput, k=Depends(key)):
        return evolution.create(body, k)

    @api.post("/evolution/experiments/{id}/approve")
    def approve_experiment(id: str, body: EvolutionApproval):
        return evolution.approve(id, body.candidate)

    @api.post("/evolution/experiments/{id}/rollback")
    def rollback_experiment(id: str):
        return evolution.rollback(id)

    @api.get("/cognition/snapshot")
    def cognition():
        return {
            "memories": service.list("memory"),
            "courses": service.list("course"),
            "pending_turns": [
                x for x in service.list("turn") if x["status"] == "pending"
            ],
            "layers": ["perception", "workspace", "self", "consolidated"],
            "projection_only": True,
        }

    @api.get("/events")
    def events(
        after: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=1000),
    ):
        with db.sessions() as s:
            return [
                {
                    "seq": e.seq,
                    "type": e.type,
                    "payload": json.loads(e.payload),
                    "created_at": e.created_at,
                }
                for e in s.scalars(
                    select(Event)
                    .where(Event.scope == "owner", Event.seq > after)
                    .order_by(Event.seq)
                    .limit(limit)
                )
            ]

    @api.get("/events/head")
    def events_head():
        with db.sessions() as s:
            value = s.scalar(
                select(Event.seq)
                .where(Event.scope == "owner")
                .order_by(Event.seq.desc())
                .limit(1)
            )
        return {"seq": value or 0}

    @api.get("/stream")
    async def stream(
        after: int = Query(default=0, ge=0),
        last_event_id: str | None = Header(default=None),
    ):
        if last_event_id:
            try:
                after = max(after, int(last_event_id))
            except ValueError:
                fail(422, "invalid_event_cursor")

        async def generate():
            cursor = after
            while True:
                batch = events(cursor, 100)
                for event in batch:
                    cursor = event["seq"]
                    yield f'id: {cursor}\nevent: {event["type"]}\ndata: {json.dumps(event)}\n\n'
                if not batch:
                    yield ": heartbeat\n\n"
                await asyncio.sleep(1)

        return StreamingResponse(generate(), media_type="text/event-stream")

    @api.post("/mac/runs")
    def mac():
        fail(501, "mac_execution_not_implemented_no_actions_performed")

    @api.post("/calls")
    def calls():
        fail(501, "media_transport_not_implemented")

    app.mount("/v2", api)
    root = Path(
        os.getenv(
            "FAIRY_WEB_ROOT", str(Path(__file__).resolve().parents[2] / "apps/web")
        )
    )
    if root.exists():
        app.mount("/assets", StaticFiles(directory=root), name="assets")

        @app.get("/")
        def home():
            return FileResponse(root / "index.html")

        @app.get("/service-worker.js")
        def service_worker():
            return FileResponse(
                root / "service-worker.js",
                media_type="application/javascript",
                headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"},
            )

    return app
