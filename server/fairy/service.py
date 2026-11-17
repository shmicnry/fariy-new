from __future__ import annotations
import hashlib
import json
from datetime import datetime, timezone, timedelta
from sqlalchemy import select
from fastapi import HTTPException
from .store import Record, Request, view, now, uid
from .cognition import relevance, rrf


def fail(status, detail):
    raise HTTPException(status, detail)


def digest(data):
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


class Service:
    def __init__(self, store):
        self.db = store

    def rows(self, s, kind, scope="owner"):
        return s.scalars(
            select(Record)
            .where(Record.scope == scope, Record.kind == kind)
            .order_by(Record.created_at, Record.id)
        ).all()

    def get(self, s, id, kind=None):
        r = s.get(Record, id)
        if not r or r.scope != "owner" or (kind and r.kind != kind):
            fail(404, "record_not_found")
        return r

    def replay(self, s, key, body):
        r = s.scalar(
            select(Request).where(Request.scope == "owner", Request.key == key)
        )
        if r:
            if r.digest != digest(body):
                fail(409, "idempotency_key_reused_with_different_body")
            return self.resolve_cached(s, json.loads(r.result))

    def resolve_cached(self, s, result):
        if isinstance(result, list):
            return [self.resolve_cached(s, x) for x in result]
        if isinstance(result, dict):
            if result.get("id"):
                record = s.get(Record, result["id"])
                if record and record.status in ("deleted", "invalidated"):
                    return {
                        "id": record.id,
                        "status": record.status,
                        "revision": record.revision,
                    }
                if record and record.kind in (
                    "memory",
                    "memory_proposal",
                    "link_import",
                ):
                    return view(record)
                if record and record.kind in (
                    "quiz",
                    "world_claim",
                    "assessment_attempt",
                ):
                    current = view(record)
                    data = json.loads(record.payload)
                    refs = [
                        s.get(Record, source_id)
                        for source_id in data.get("source_ids", [])
                    ]
                    current["source_eligible"] = all(
                        self.source_eligible(ref) for ref in refs
                    )
                    return current
            return {k: self.resolve_cached(s, v) for k, v in result.items()}
        return result

    def remember_result(self, s, key, body, result):
        s.add(
            Request(
                id=uid(),
                scope="owner",
                key=key,
                digest=digest(body),
                result=json.dumps(result),
            )
        )

    def list(self, kind):
        with self.db.sessions() as s:
            return [
                view(r)
                for r in self.rows(s, kind)
                if r.status not in ("deleted", "invalidated")
            ]

    def create(self, kind, payload, key):
        with self.db.tx() as s:
            body = {"kind": kind, **payload}
            cached = self.replay(s, key, body)
            if cached is not None:
                return cached
            r = self.db.add(s, "owner", kind, payload)
            self.db.emit(s, "owner", kind + ".created", {"id": r.id})
            result = view(r)
            self.remember_result(s, key, body, result)
            return result

    def source_eligible(self, r):
        if not r or r.status not in ("active", "completed"):
            return False
        quality = json.loads(r.payload).get("quality", {})
        if quality.get("rating") in ("disputed", "rejected"):
            return False
        expiry = quality.get("expires_at")
        return not expiry or datetime.fromisoformat(expiry) > datetime.now(timezone.utc)

    def recall(self, query, principal="confirmed"):
        if principal != "confirmed":
            return {"results": [], "reason": "private_recall_denied", "degraded": False}
        with self.db.sessions() as s:
            items = []
            for r in self.rows(s, "memory"):
                if r.status != "active":
                    continue
                data = json.loads(r.payload)
                refs = [s.get(Record, id) for id in data["source_ids"]]
                if not refs or any(
                    not x or x.scope != "owner" or not self.source_eligible(x)
                    for x in refs
                ):
                    continue
                score = relevance(query, data["text"])
                if score >= 0.25:
                    items.append((r, score))
            items.sort(key=lambda x: (-x[1], x[0].id))
            ranked = rrf([r.id for r, _ in items[:60]])
            byid = {r.id: (r, score) for r, score in items}
            return {
                "results": [
                    dict(view(byid[id][0]), relevance=byid[id][1]) for id in ranked[:12]
                ],
                "reason": "matched" if ranked else "no_match_not_proof_of_absence",
                "degraded": True,
                "retrieval_mode": "local_character_vector_hybrid",
            }

    def model_context(self, query):
        """Whole entries, bounded by characters; snapshot fences writes after source changes."""
        recalled = self.recall(query)["results"]
        with self.db.sessions() as s:
            entries, snapshot, used, omitted = [], {}, 0, 0
            candidates = []
            for memory in recalled:
                candidates.append(
                    (
                        self.get(s, memory["id"]),
                        {
                            "kind": "quoted_memory",
                            "id": memory["id"],
                            "text": memory["text"],
                            "source_ids": memory["source_ids"],
                        },
                    )
                )
            for turn in self.rows(s, "turn")[-6:]:
                if turn.status == "completed":
                    d = json.loads(turn.payload)
                    candidates.append(
                        (
                            turn,
                            {
                                "kind": "recent_dialogue",
                                "source_ids": d.get("source_ids", []),
                                "user": d["text"],
                                "assistant": d.get("reply", ""),
                            },
                        )
                    )
            for row, entry in candidates:
                data = json.loads(row.payload)
                ids = [row.id] + data.get("source_ids", [])
                refs = [s.get(Record, id) for id in ids]
                if any(not self.source_eligible(x) for x in refs):
                    continue
                encoded = json.dumps(entry, ensure_ascii=False)
                if used + len(encoded) > 12000:
                    omitted += 1
                    continue
                used += len(encoded)
                entries.append(entry)
                snapshot.update({x.id: x.revision for x in refs})
            return {
                "entries": entries,
                "omitted": omitted,
                "budget_unit": "characters",
            }, snapshot

    def memory(self, text, sources, key):
        with self.db.tx() as s:
            body = {"text": text, "source_ids": sources}
            cached = self.replay(s, key, body)
            if cached is not None:
                return cached
            if not sources:
                fail(422, "evidence_required")
            for id in sources:
                r = self.get(s, id)
                if r.kind not in ("evidence", "material") or r.status != "active":
                    fail(422, "invalid_source")
                if text not in json.loads(r.payload).get("text", ""):
                    fail(422, "exact_source_quote_required")
            r = self.db.add(s, "owner", "memory", body)
            self.db.emit(s, "owner", "memory.created", {"id": r.id})
            result = view(r)
            self.remember_result(s, key, body, result)
            return result

    def invalidate(self, id, revision):
        with self.db.tx() as s:
            return self._invalidate(s, id, revision)

    def _invalidate(self, s, id, revision):
        r = self.get(s, id)
        if r.revision != revision:
            fail(409, "revision_conflict")
        r.status = "deleted"
        r.revision += 1
        # Explicit erasure of content; downstream proposals cannot read a retained hidden copy.
        r.payload = json.dumps({"deleted_at": now()})
        invalid = {id}
        while True:
            added = set()
            for child in s.scalars(select(Record).where(Record.scope == "owner")).all():
                data = json.loads(child.payload)
                if child.status not in ("deleted", "invalidated") and (
                    set(data.get("source_ids", [])) & invalid
                ):
                    child.status = "invalidated"
                    child.revision += 1
                    child.payload = json.dumps({"invalidated_by": id})
                    added.add(child.id)
            if not added:
                break
            invalid |= added
        for cached in s.scalars(select(Request).where(Request.scope == "owner")).all():
            cached.result = json.dumps(
                self.resolve_cached(s, json.loads(cached.result))
            )
        self.db.emit(s, "owner", "sources.invalidated", {"ids": sorted(invalid)})
        return {
            "deleted": id,
            "affected": sorted(invalid),
            "provider_and_backup_erasure": False,
        }

    def start_turn(self, text, key, routing="auto"):
        with self.db.tx() as s:
            body = {"text": text, "routing": routing}
            cached = self.replay(s, key, body)
            if cached is not None:
                return dict(cached, _replayed=True)
            if any(r.status == "pending" for r in self.rows(s, "turn")):
                fail(409, "scope_has_pending_turn")
            ev = self.db.add(
                s,
                "owner",
                "evidence",
                {"text": text, "speaker": "owner", "source_type": "user_statement"},
            )
            r = self.db.add(
                s,
                "owner",
                "turn",
                {
                    "text": text,
                    "evidence_id": ev.id,
                    "source_ids": [ev.id],
                    "generation": 1,
                    "routing": routing,
                },
                "pending",
            )
            self.db.emit(
                s, "owner", "input.received", {"turn_id": r.id, "evidence_id": ev.id}
            )
            result = view(r)
            self.remember_result(s, key, body, result)
            return result

    def finish_turn(
        self, id, text=None, error=None, snapshot=None, metadata=None, proposals=None
    ):
        with self.db.tx() as s:
            r = self.get(s, id, "turn")
            if r.status != "pending":
                return view(r)
            data = json.loads(r.payload)
            for source_id, revision in (snapshot or {}).items():
                source = s.get(Record, source_id)
                if (
                    not source
                    or not self.source_eligible(source)
                    or source.revision != revision
                ):
                    error = "context_snapshot_invalidated"
                    text = None
            data["source_ids"] = list(
                dict.fromkeys(data.get("source_ids", []) + list(snapshot or {}))
            )
            r.status = "failed" if error else "completed"
            data.update(reply=text, error=error)
            if metadata:
                data["model_route"] = metadata
            if not error:
                data["memory_proposal_ids"] = self._commit_memory_proposals(
                    s, r, proposals or []
                )
                text = self.ground_memory_reply(
                    text, data["memory_proposal_ids"], data.get("text", "")
                )
                data["reply"] = text
                data["memory_receipt"] = {
                    "status": (
                        "pending_review"
                        if data["memory_proposal_ids"]
                        else "not_written"
                    ),
                    "long_term_memory_written": False,
                }
                self.db.emit(
                    s,
                    "owner",
                    "memory.receipt",
                    {"turn_id": id, **data["memory_receipt"]},
                )
            r.payload = json.dumps(data)
            r.revision += 1
            if not error:
                self.db.add(
                    s,
                    "owner",
                    "round",
                    {"turn_id": id, "source_ids": [id], "index": 1, "reply": text},
                )
                # Understanding and durable transcript are independent from long-term facts and actions.
                self.db.emit(s, "owner", "input.processed", {"turn_id": id})
                self.db.emit(
                    s,
                    "owner",
                    "transcript.committed",
                    {"turn_id": id, "long_term_memory_written": False},
                )
            self.db.emit(
                s,
                "owner",
                "turn." + r.status,
                {"turn_id": id, "action_executed": False},
            )
            return view(r)

    def _commit_memory_proposals(self, s, turn, candidates):
        return []

    def ground_memory_reply(self, text, proposal_ids, user_text=""):
        return text

    def cancel(self, id):
        with self.db.tx() as s:
            r = self.get(s, id, "turn")
            data = json.loads(r.payload)
            if r.status == "pending":
                r.status = "interrupted"
                data["generation"] += 1
                r.payload = json.dumps(data)
                r.revision += 1
                self.db.emit(
                    s,
                    "owner",
                    "turn.interrupted",
                    {"turn_id": id, "generation": data["generation"]},
                )
            return view(r)

    def custom_card(self, title, text, subtype, remind_at, key):
        if subtype not in ("note", "todo", "reminder", "anniversary"):
            fail(422, "custom_card_cannot_authorize_actions")
        if remind_at:
            try:
                if datetime.fromisoformat(remind_at).tzinfo is None:
                    raise ValueError()
            except ValueError:
                fail(422, "reminder_requires_timezone")
        return self.create(
            "card",
            {
                "title": title,
                "text": text,
                "type": "custom",
                "subtype": subtype,
                "remind_at": remind_at,
                "choices": [],
                "action_authority": False,
            },
            key,
        )

    def material(self, title, text, key, request_body=None):
        with self.db.tx() as s:
            body = request_body or {"title": title, "text": text}
            cached = self.replay(s, key, body)
            if cached is not None:
                return cached
            material = self.db.add(
                s,
                "owner",
                "material",
                {"title": title, "text": text, "source_type": "user_upload"},
            )
            course = self.db.add(
                s,
                "owner",
                "course",
                {
                    "title": title,
                    "source_ids": [material.id],
                    "stage": "queued",
                    "mastered": False,
                    "steps_verified": 0,
                    "steps_total": 3,
                },
            )
            self.db.add(
                s,
                "owner",
                "job",
                {
                    "type": "study_text",
                    "course_id": course.id,
                    "source_ids": [material.id],
                    "checkpoint": 0,
                    "attempts": 0,
                    "lease_until": None,
                },
                "queued",
            )
            self.db.emit(s, "owner", "learning.queued", {"course_id": course.id})
            result = {"material": view(material), "course": view(course)}
            self.remember_result(s, key, body, result)
            return result

    def acquire(self, course_id, key):
        with self.db.tx() as s:
            course = self.get(s, course_id, "course")
            d = json.loads(course.payload)
            if course.status != "active" or not d.get("mastered"):
                fail(409, "course_not_verified")
            if any(not self.source_eligible(self.get(s, x)) for x in d["source_ids"]):
                fail(409, "source_not_eligible")
            if d.get("practice_required"):
                reviewed = [
                    x
                    for x in self.rows(s, "practice")
                    if x.status == "active"
                    and json.loads(x.payload).get("course_id") == course_id
                    and json.loads(x.payload).get("evaluation") != "ungraded"
                ]
                reviewed.sort(
                    key=lambda x: json.loads(x.payload).get("reviewed_at", "")
                )
                if (
                    not reviewed
                    or json.loads(reviewed[-1].payload).get("evaluation") != "passed"
                ):
                    fail(409, "practice_not_currently_passed")
            body = {"course_id": course_id}
            old = self.replay(s, key, body)
            if old is not None:
                return old
            existing = [
                r
                for r in self.rows(s, "acquired_skill")
                if json.loads(r.payload).get("course_id") == course_id
                and r.status == "active"
            ]
            if existing:
                return view(existing[0])
            r = self.db.add(
                s,
                "owner",
                "acquired_skill",
                {
                    "course_id": course_id,
                    "title": d["title"],
                    "source_ids": d["source_ids"],
                    "summary": d.get("notes", ""),
                    "provenance": "user_learned",
                    "executable": False,
                },
            )
            self.db.emit(s, "owner", "skill.acquired", {"id": r.id})
            result = view(r)
            self.remember_result(s, key, body, result)
            return result

    def assess(self, id, revision, passed, evidence):
        with self.db.tx() as s:
            r = self.get(s, id, "course")
            d = json.loads(r.payload)
            if r.status != "active" or r.revision != revision:
                fail(409, "revision_conflict")
            if d["stage"] not in ("awaiting_assessment", "needs_practice"):
                fail(409, "course_not_ready")
            if not evidence.strip():
                fail(422, "assessment_evidence_required")
            if any(not self.source_eligible(self.get(s, x)) for x in d["source_ids"]):
                fail(409, "source_invalidated")
            if passed and d.get("practice_required"):
                reviewed = [
                    x
                    for x in self.rows(s, "practice")
                    if x.status == "active"
                    and json.loads(x.payload).get("course_id") == id
                    and json.loads(x.payload).get("evaluation") != "ungraded"
                ]
                reviewed.sort(
                    key=lambda x: json.loads(x.payload).get("reviewed_at", "")
                )
                if (
                    not reviewed
                    or json.loads(reviewed[-1].payload).get("evaluation") != "passed"
                ):
                    fail(409, "reviewed_practice_required")
                if not any(
                    evidence
                    in json.loads(self.get(s, source_id).payload).get("text", "")
                    for source_id in d["source_ids"]
                ):
                    fail(422, "exact_source_quote_required")
            d.update(
                stage="completed" if passed else "needs_practice",
                mastered=passed,
                assessment={"method": "owner_review", "evidence": evidence},
                steps_verified=3 if passed else 2,
            )
            r.payload = json.dumps(d)
            r.revision += 1
            self.db.emit(s, "owner", "learning.assessed", {"id": id, "passed": passed})
            return view(r)

    def configure(self, revision, data):
        if data.get("autonomous_paid"):
            fail(422, "capability_not_implemented_cannot_enable")
        if data.get("mac_execute") and not data.get("mac_allowed_apps"):
            fail(422, "mac_execute_requires_allowed_apps")
        if not 0 <= data.get("daily_minutes", 45) <= 240:
            fail(422, "invalid_daily_budget")
        with self.db.tx() as s:
            rows = [r for r in self.rows(s, "config") if r.status == "active"]
            if rows:
                r = rows[0]
                if r.revision != revision:
                    fail(409, "revision_conflict")
                r.revision += 1
                r.payload = json.dumps(data)
            else:
                if revision != 0:
                    fail(409, "revision_conflict")
                r = self.db.add(s, "owner", "config", data)
            self.db.emit(s, "owner", "config.updated", {"revision": r.revision})
            return view(r)

    def propose_note(self, title, text, key):
        with self.db.tx() as s:
            body = {"title": title, "text": text, "action": "save_note"}
            old = self.replay(s, key, body)
            if old is not None:
                return old
            r = self.db.add(
                s,
                "owner",
                "approval",
                {
                    "title": title,
                    "text": text,
                    "action": "save_note",
                    "digest": digest(body),
                    "expires_at": (
                        datetime.now(timezone.utc) + timedelta(minutes=5)
                    ).isoformat(),
                    "decision": None,
                },
            )
            self.db.emit(s, "owner", "approval.proposed", {"id": r.id})
            result = view(r)
            self.remember_result(s, key, body, result)
            return result

    def choose_note(self, id, revision, action_digest, choice, key):
        with self.db.tx() as s:
            body = {
                "id": id,
                "revision": revision,
                "digest": action_digest,
                "choice": choice,
            }
            old = self.replay(s, key, body)
            if old is not None:
                return old
            r = self.get(s, id, "approval")
            d = json.loads(r.payload)
            if (
                r.status != "active"
                or r.revision != revision
                or d.get("decision") is not None
            ):
                fail(409, "approval_already_changed")
            if d["digest"] != action_digest:
                fail(409, "action_digest_mismatch")
            if datetime.fromisoformat(d["expires_at"]) <= datetime.now(timezone.utc):
                fail(409, "approval_expired")
            if choice not in ("allow_once", "reject"):
                fail(422, "unsupported_choice")
            d["decision"] = choice
            if choice == "allow_once":
                # Only this deterministic internal action is implemented. Never dispatch arbitrary model tools.
                artifact = self.db.add(
                    s,
                    "owner",
                    "note",
                    {
                        "title": d["title"],
                        "text": d["text"],
                        "approval_id": id,
                        "source_ids": [id],
                    },
                )
                d["artifact_id"] = artifact.id
                self.db.emit(
                    s,
                    "owner",
                    "action.executed",
                    {
                        "approval_id": id,
                        "artifact_id": artifact.id,
                        "surface": "database_note",
                    },
                )
            r.payload = json.dumps(d)
            r.revision += 1
            self.db.emit(s, "owner", "approval.resolved", {"id": id, "choice": choice})
            result = view(r)
            self.remember_result(s, key, body, result)
            return result
