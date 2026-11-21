"""Reviewed facts, immutable revision snapshots and conservative forgetting barriers."""

from __future__ import annotations

import hashlib
import json
import re
from .service import Service, fail
from .store import Request, view, now
from .identity import infer_subject, normalized_fact, personal_question


class MemoryService(Service):
    def ground_memory_reply(self, text, proposal_ids, user_text=""):
        if (
            proposal_ids
            and re.match(
                r"^(?:请(?:帮我)?记住|帮我记住|记住|请记下)", user_text.strip()
            )
            and not re.search(r"[？?]", user_text)
        ):
            return (
                f"已生成 {len(proposal_ids)} 条关于你的待审阅记忆提案，确认后才会保存。"
            )
        # Known write assertions are replaced with the actual domain receipt. This is
        # bounded wording validation, not a claim to detect every semantic hallucination.
        claim = re.compile(
            r"我(?:已经|已)?(?:记住|记下|保存|存储)(?:了|好)|(?:已经|已)(?:记住|记下|保存|存储)|我会(?:一直|永久|永远)记住|I(?:'ve| have)? (?:saved|stored|remembered)|I'll remember",
            re.I,
        )
        if not text or not claim.search(text):
            return text
        remainder = "".join(
            sentence
            for sentence in re.split(r"(?<=[。！？.!?])", text)
            if not claim.search(sentence)
        ).strip()
        receipt = (
            f"已生成 {len(proposal_ids)} 条待审阅记忆提案，确认后才会保存。"
            if proposal_ids
            else "本轮没有写入长期记忆。"
        )
        return receipt + ("\n\n" + remainder if remainder else "")

    def __init__(self, store):
        super().__init__(store)
        with self.db.tx() as s:
            if not self.rows(s, "memory_policy"):
                self.db.add(s, "owner", "memory_policy", {"suppressed_source_ids": []})

    def policy(self, s):
        return self.rows(s, "memory_policy")[0]

    def bump_policy(self, s, suppress=()):
        p = self.policy(s)
        d = json.loads(p.payload)
        d["suppressed_source_ids"] = sorted(
            set(d["suppressed_source_ids"]) | set(suppress)
        )
        p.payload = json.dumps(d)
        p.revision += 1

    def recall_query(self, query):
        return "喜欢 喝" if personal_question(query) == "owner" else query

    def model_context(self, query, recalled=None):
        with self.db.sessions() as s:
            policy = self.policy(s)
            policy_id, policy_revision = policy.id, policy.revision
            suppressed = set(json.loads(policy.payload)["suppressed_source_ids"])
        target = personal_question(query)
        context, snapshot = super().model_context(
            self.recall_query(query), recalled=recalled
        )
        context["entries"] = [
            entry
            for entry in context["entries"]
            if entry["kind"] != "recent_dialogue"
            or not set(entry.get("source_ids", [])) & suppressed
        ]
        with self.db.sessions() as s:
            for entry in context["entries"]:
                if entry["kind"] != "quoted_memory":
                    continue
                record = self.get(s, entry["id"], "memory")
                data = json.loads(record.payload)
                quote = entry.pop("text")
                subject = data.get("subject", infer_subject(quote))
                entry.update(
                    subject=subject,
                    speaker="owner",
                    quote=quote,
                    statement=normalized_fact(quote, subject),
                    review_status="confirmed",
                )
        context.update(speaker="owner", speaker_label="当前用户")
        if target:
            context.update(query_subject=target, intent="personal_drink_preference")
            context["entries"] = [
                e
                for e in context["entries"]
                if e["kind"] == "quoted_memory" and e.get("subject") == target
            ]
        if not target:
            from .knowledge import KnowledgeService
            from .cognition import relevance

            with self.db.sessions() as s:
                for claim in KnowledgeService(self.db).world():
                    if (
                        not claim["source_eligible"]
                        or relevance(
                            query,
                            claim["subject"] + claim["predicate"] + claim["value"],
                        )
                        < 0.25
                    ):
                        continue
                    if len(context["entries"]) >= 20:
                        break
                    source = self.get(s, claim["source_ids"][0])
                    context["entries"].append(
                        {
                            "kind": "world_claim",
                            "subject": claim["subject"],
                            "predicate": claim["predicate"],
                            "value": claim["value"],
                            "quote": claim["quote"],
                            "verification": claim["verification"],
                            "source_quality": claim["source_quality"],
                            "conflicts_with": claim["conflicts_with"],
                            "source_ids": claim["source_ids"],
                        }
                    )
                    snapshot[claim["id"]] = claim["revision"]
                    snapshot[source.id] = source.revision
        snapshot[policy_id] = policy_revision
        return context, snapshot

    def _snapshot_revision(self, s, memory):
        d = json.loads(memory.payload)
        existing = [
            r
            for r in self.rows(s, "memory_revision")
            if json.loads(r.payload).get("memory_id") == memory.id
            and json.loads(r.payload).get("memory_revision") == memory.revision
        ]
        if existing:
            return existing[0]
        return self.db.add(
            s,
            "owner",
            "memory_revision",
            {
                "memory_id": memory.id,
                "memory_revision": memory.revision,
                "text": d["text"],
                "subject": d.get("subject", infer_subject(d["text"])),
                "statement": normalized_fact(
                    d["text"], d.get("subject", infer_subject(d["text"]))
                ),
                "category": d.get("category", "fact"),
                "source_ids": d["source_ids"],
                "valid_from": d.get("valid_from", memory.created_at),
                "valid_to": None,
                "change_reason": d.get("change_reason", "initial_review"),
            },
        )

    def _create_proposal(self, s, text, source_id, category="fact"):
        source = self.get(s, source_id)
        if source.kind not in ("evidence", "material") or not self.source_eligible(
            source
        ):
            fail(422, "invalid_source")
        if not text.strip() or text not in json.loads(source.payload).get("text", ""):
            fail(422, "exact_source_quote_required")
        if source_id in json.loads(self.policy(s).payload)["suppressed_source_ids"]:
            fail(409, "source_suppressed_register_new_statement")
        existing = [
            r
            for r in self.rows(s, "memory_proposal")
            if r.status in ("pending", "approved")
            and json.loads(r.payload).get("source_ids") == [source_id]
            and json.loads(r.payload).get("text") == text
        ]
        if existing:
            return existing[0]
        r = self.db.add(
            s,
            "owner",
            "memory_proposal",
            {
                "text": text,
                "category": category,
                "subject": infer_subject(text),
                "statement": normalized_fact(text, infer_subject(text)),
                "source_ids": [source_id],
            },
            "pending",
        )
        self.db.emit(
            s, "owner", "memory.proposed", {"id": r.id, "source_id": source_id}
        )
        return r

    def propose(self, text, source_id, key):
        with self.db.tx() as s:
            body = {"op": "memory.propose", "text": text, "source_id": source_id}
            old = self.replay(s, key, body)
            if old is not None:
                return old
            r = self._create_proposal(s, text, source_id)
            result = view(r)
            self.remember_result(s, key, body, result)
            return result

    def _commit_memory_proposals(self, s, turn, candidates):
        source_id = json.loads(turn.payload)["evidence_id"]
        source = self.get(s, source_id)
        original = json.loads(source.payload).get("text", "")
        result = []
        for candidate in candidates[:6]:
            text = candidate.get("quote", "")
            if not text.strip() or len(text) > 500 or text not in original:
                self.db.emit(
                    s,
                    "owner",
                    "memory.proposal_discarded",
                    {"turn_id": turn.id, "reason": "unquoted_candidate"},
                )
                continue
            if source_id in json.loads(self.policy(s).payload)["suppressed_source_ids"]:
                continue
            proposal = self._create_proposal(
                s, text, source_id, candidate.get("category", "fact")
            )
            result.append(proposal.id)
        return list(dict.fromkeys(result))

    def review(self, id, revision, decision, key, subject=None):
        with self.db.tx() as s:
            body = {
                "op": "memory.review",
                "id": id,
                "revision": revision,
                "decision": decision,
                "subject": subject,
            }
            old = self.replay(s, key, body)
            if old is not None:
                return old
            r = self.get(s, id, "memory_proposal")
            d = json.loads(r.payload)
            if r.status != "pending" or r.revision != revision:
                fail(409, "proposal_already_changed")
            if decision not in ("approve", "reject"):
                fail(422, "invalid_decision")
            for source_id in d["source_ids"]:
                source = self.get(s, source_id)
                if not self.source_eligible(source) or d["text"] not in json.loads(
                    source.payload
                ).get("text", ""):
                    fail(409, "source_invalidated")
                if (
                    source_id
                    in json.loads(self.policy(s).payload)["suppressed_source_ids"]
                ):
                    fail(409, "source_suppressed")
            d["subject"] = subject or d.get("subject", infer_subject(d["text"]))
            d["statement"] = normalized_fact(d["text"], d["subject"])
            r.status = "approved" if decision == "approve" else "rejected"
            r.revision += 1
            if decision == "approve":
                matches = [
                    m
                    for m in self.rows(s, "memory")
                    if m.status == "active"
                    and json.loads(m.payload).get("text") == d["text"]
                    and json.loads(m.payload).get("source_ids") == d["source_ids"]
                ]
                memory = (
                    matches[0]
                    if matches
                    else self.db.add(
                        s,
                        "owner",
                        "memory",
                        {
                            "text": d["text"],
                            "category": d.get("category", "fact"),
                            "source_ids": d["source_ids"],
                            "reviewed": True,
                            "subject": d["subject"],
                            "statement": d["statement"],
                            "valid_from": now(),
                            "origin_proposal_id": id,
                        },
                    )
                )
                self._snapshot_revision(s, memory)
                d["memory_id"] = memory.id
                self.bump_policy(s)
            r.payload = json.dumps(d)
            self.db.emit(
                s,
                "owner",
                "memory.reviewed",
                {"id": id, "decision": decision, "memory_id": d.get("memory_id")},
            )
            result = view(r)
            self.remember_result(s, key, body, result)
            return result

    def memory(self, text, sources, key):
        # Explicit legacy/manual save is itself an owner review; preserve endpoint compatibility.
        with self.db.tx() as s:
            body = {"text": text, "source_ids": sources}
            old = self.replay(s, key, body)
            if old is not None:
                return old
            if not sources:
                fail(422, "evidence_required")
            for id in sources:
                source = self.get(s, id)
                if source.kind not in (
                    "evidence",
                    "material",
                ) or not self.source_eligible(source):
                    fail(422, "invalid_source")
                if text not in json.loads(source.payload).get("text", ""):
                    fail(422, "exact_source_quote_required")
                if id in json.loads(self.policy(s).payload)["suppressed_source_ids"]:
                    fail(409, "source_suppressed")
            r = self.db.add(
                s,
                "owner",
                "memory",
                dict(
                    body,
                    reviewed=True,
                    subject=infer_subject(text),
                    statement=normalized_fact(text, infer_subject(text)),
                    valid_from=now(),
                ),
            )
            self._snapshot_revision(s, r)
            self.bump_policy(s)
            self.db.emit(s, "owner", "memory.created", {"id": r.id})
            result = view(r)
            self.remember_result(s, key, body, result)
            return result

    def _stale_dialogue(self, s, ids):
        affected = set(ids)
        while True:
            added = set()
            for row in self.rows(s, "turn") + self.rows(s, "round"):
                if row.status in ("deleted", "invalidated"):
                    continue
                if set(json.loads(row.payload).get("source_ids", [])) & affected:
                    row.status = "invalidated"
                    row.revision += 1
                    row.payload = json.dumps(
                        {
                            "invalidated_at": now(),
                            "reason": "memory_corrected_or_forgotten",
                        }
                    )
                    added.add(row.id)
            if not added:
                break
            affected |= added
        return affected - set(ids)

    def _scrub_cached(self, s):
        for cached in s.query(Request).filter(Request.scope == "owner"):
            cached.result = json.dumps(
                self.resolve_cached(s, json.loads(cached.result))
            )

    def _purge_embeddings(self, s, texts):
        # Derived vectors of removed text must not survive as a hidden copy.
        hashes = {
            hashlib.sha256(t.encode("utf-8")).hexdigest() for t in texts if t
        }
        if not hashes:
            return
        for row in self.rows(s, "embedding_cache"):
            key = json.loads(row.payload).get("key", "")
            if key.rsplit(":", 1)[-1] in hashes:
                s.delete(row)

    def correct(self, id, revision, text, reason, key, subject=None):
        if not text.strip() or not reason.strip():
            fail(422, "correction_and_reason_required")
        with self.db.tx() as s:
            body = {
                "op": "memory.correct",
                "subject": subject,
                "id": id,
                "revision": revision,
                "text": text,
                "reason": reason,
            }
            old = self.replay(s, key, body)
            if old is not None:
                return old
            r = self.get(s, id, "memory")
            d = json.loads(r.payload)
            if r.status != "active" or r.revision != revision:
                fail(409, "revision_conflict")
            if text == d["text"] and (
                subject is None or subject == d.get("subject", infer_subject(text))
            ):
                fail(422, "correction_unchanged")
            previous_text = d["text"]
            previous = self._snapshot_revision(s, r)
            prev = json.loads(previous.payload)
            prev["valid_to"] = now()
            previous.payload = json.dumps(prev)
            old_sources = d["source_ids"]
            source = self.db.add(
                s,
                "owner",
                "evidence",
                {
                    "text": text,
                    "speaker": "owner",
                    "source_type": "owner_correction",
                    "memory_id": id,
                },
            )
            d.update(
                text=text,
                subject=subject or infer_subject(text),
                statement=normalized_fact(text, subject or infer_subject(text)),
                source_ids=[source.id],
                reviewed=True,
                valid_from=now(),
                change_reason=reason,
            )
            self._purge_embeddings(s, [previous_text])
            r.payload = json.dumps(d)
            r.revision += 1
            self._snapshot_revision(s, r)
            self.bump_policy(s, old_sources)
            stale = self._stale_dialogue(s, set(old_sources) | {id})
            self._scrub_cached(s)
            self.db.emit(
                s,
                "owner",
                "memory.corrected",
                {
                    "id": id,
                    "revision": r.revision,
                    "invalidated_turn_ids": sorted(stale),
                },
            )
            result = view(r)
            self.remember_result(s, key, body, result)
            return result

    def history(self, id):
        with self.db.sessions() as s:
            memory = self.get(s, id, "memory")
            if memory.status in ("deleted", "invalidated"):
                return []
            rows = [
                view(r)
                for r in self.rows(s, "memory_revision")
                if r.status == "active" and json.loads(r.payload).get("memory_id") == id
            ]
            if not rows:
                return [
                    dict(view(memory), memory_revision=memory.revision, valid_to=None)
                ]
            return sorted(rows, key=lambda r: r["memory_revision"])

    def invalidate(self, id, revision):
        with self.db.tx() as s:
            r = self.get(s, id)
            suppress = {id}
            if r.kind == "memory":
                versions = [
                    v
                    for v in self.rows(s, "memory_revision")
                    if json.loads(v.payload).get("memory_id") == id
                ]
                self._purge_embeddings(
                    s,
                    [json.loads(r.payload).get("text")]
                    + [json.loads(v.payload).get("text") for v in versions],
                )
                suppress |= set(json.loads(r.payload).get("source_ids", []))
                for v in versions:
                    suppress |= set(json.loads(v.payload).get("source_ids", []))
                result = self._invalidate(s, id, revision)
                extra_affected = set()
                for v in versions:
                    v.status = "deleted"
                    v.revision += 1
                    v.payload = json.dumps({"memory_id": id, "deleted_at": now()})
                    extra_affected.add(v.id)
                for p in self.rows(s, "memory_proposal"):
                    d = json.loads(p.payload)
                    if d.get("memory_id") == id or (
                        p.status == "pending"
                        and set(d.get("source_ids", [])) & suppress
                    ):
                        p.status = "invalidated"
                        p.revision += 1
                        p.payload = json.dumps({"invalidated_by": id})
                        extra_affected.add(p.id)
                extra_affected |= self._stale_dialogue(s, suppress)
                result["affected"] = sorted(set(result["affected"]) | extra_affected)
            else:
                if r.kind not in (
                    "evidence",
                    "material",
                    "card",
                    "approval",
                    "note",
                    "acquired_skill",
                    "course",
                    "quiz",
                    "world_claim",
                ):
                    fail(422, "record_kind_not_deletable")
                result = self._invalidate(s, id, revision)
                if r.kind == "world_claim":
                    extra_affected = self._stale_dialogue(s, {id})
                    result["affected"] = sorted(
                        set(result["affected"]) | extra_affected
                    )
            self.bump_policy(s, suppress)
            self._scrub_cached(s)
            return result
