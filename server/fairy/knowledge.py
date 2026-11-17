"""Owner-reviewed source quality, grounded world claims and course evaluation."""

import json
from datetime import datetime, timezone
from .learning import LearningService
from .service import fail
from .store import view, now


class KnowledgeService(LearningService):
    def _notify_revision(self, s):
        for epoch in self.rows(s, "memory_policy"):
            epoch.revision += 1

    def _revoke_course(self, s, course, reason):
        data = json.loads(course.payload)
        data.update(
            mastered=False,
            stage="needs_practice",
            steps_verified=min(data.get("steps_verified", 0), 2),
            revocation={"reason": reason, "revoked_at": now()},
        )
        course.payload = json.dumps(data)
        course.revision += 1
        revoked_skills = []
        for skill in self.rows(s, "acquired_skill"):
            skill_data = json.loads(skill.payload)
            if skill.status == "active" and skill_data.get("course_id") == course.id:
                skill.status = "invalidated"
                skill.revision += 1
                skill.payload = json.dumps(
                    {"invalidated_by_course": course.id, "reason": reason}
                )
                revoked_skills.append(skill.id)
        self.db.emit(
            s,
            "owner",
            "learning.mastery_revoked",
            {
                "course_id": course.id,
                "reason": reason,
                "acquired_skill_ids": revoked_skills,
            },
        )
        return revoked_skills

    def _reconcile_course(self, s, course_id):
        course = self.get(s, course_id, "course")
        data = json.loads(course.payload)
        if course.status != "active":
            return course
        sources_valid = all(
            self.source_eligible(self.get(s, source_id))
            for source_id in data["source_ids"]
        )
        reviewed = [
            row
            for row in self.rows(s, "practice")
            if row.status == "active"
            and json.loads(row.payload).get("course_id") == course_id
            and json.loads(row.payload).get("evaluation") != "ungraded"
        ]
        reviewed.sort(key=lambda row: json.loads(row.payload).get("reviewed_at", ""))
        latest_passed = bool(
            reviewed and json.loads(reviewed[-1].payload).get("evaluation") == "passed"
        )
        if not sources_valid:
            self._revoke_course(s, course, "source_not_eligible")
        elif reviewed and not latest_passed and data.get("mastered"):
            self._revoke_course(s, course, "latest_practice_not_passed")
        return self.get(s, course_id, "course")

    def link(self, url, title, key, collector):
        body = {"op": "link.import", "url": url, "title": title}
        with self.db.tx() as s:
            cached = self.replay(s, key, body)
            if cached is not None:
                return cached
            reservation = self.db.add(
                s, "owner", "link_import", {"url": url, "title": title}, "pending"
            )
            self.remember_result(s, key, body, view(reservation))
        try:
            content = collector(url)
        except Exception:
            with self.db.tx() as s:
                r = self.get(s, reservation.id)
                r.status = "failed"
                r.revision += 1
                r.payload = json.dumps({"url": url, "error": "link_collection_failed"})
                self.db.emit(s, "owner", "learning.link_failed", {"id": r.id})
                return view(r)
        result = self.material(title, content, "link-material-" + reservation.id)
        with self.db.tx() as s:
            r = self.get(s, result["material"]["id"])
            d = json.loads(r.payload)
            d.update(
                source_type="web_link",
                url=url,
                collected_at=now(),
                quality={"rating": "unreviewed", "reason": "尚未复核"},
            )
            r.payload = json.dumps(d)
            course = self.get(s, result["course"]["id"])
            c = json.loads(course.payload)
            c["practice_required"] = True
            course.payload = json.dumps(c)
            course.revision += 1
            imp = self.get(s, reservation.id)
            imp.status = "completed"
            imp.revision += 1
            imp.payload = json.dumps(
                {"url": url, "material_id": r.id, "course_id": result["course"]["id"]}
            )
            self.db.emit(s, "owner", "learning.link_imported", {"id": imp.id})
            return view(imp)

    def source_review(self, id, revision, rating, reason, expires_at):
        if not reason.strip():
            fail(422, "review_reason_required")
        if expires_at:
            try:
                dt = datetime.fromisoformat(expires_at)
                if dt.tzinfo is None:
                    raise ValueError()
            except ValueError:
                fail(422, "expiry_requires_timezone")
        with self.db.tx() as s:
            source = self.get(s, id, "material")
            if source.revision != revision or source.status != "active":
                fail(409, "revision_conflict")
            d = json.loads(source.payload)
            d["quality"] = {
                "rating": rating,
                "reason": reason,
                "reviewed_at": now(),
                "expires_at": expires_at,
                "method": "owner_review",
            }
            source.payload = json.dumps(d)
            source.revision += 1
            self._notify_revision(s)
            for job in self.rows(s, "job"):
                if id in json.loads(job.payload).get(
                    "source_ids", []
                ) and job.status in ("queued", "blocked"):
                    job.status = "queued" if self.source_eligible(source) else "blocked"
            if not self.source_eligible(source):
                for course in self.rows(s, "course"):
                    if id in json.loads(course.payload).get("source_ids", []):
                        self._revoke_course(s, course, "source_not_eligible")
            self.db.emit(s, "owner", "source.reviewed", {"id": id, "rating": rating})
            return view(source)

    def claim(self, subject, predicate, value, source_id, quote, key):
        with self.db.tx() as s:
            body = {
                "op": "world.claim",
                "subject": subject,
                "predicate": predicate,
                "value": value,
                "source_id": source_id,
                "quote": quote,
            }
            cached = self.replay(s, key, body)
            if cached is not None:
                return cached
            source = self.get(s, source_id, "material")
            if not self.source_eligible(source):
                fail(409, "source_not_eligible")
            if quote not in json.loads(source.payload)["text"] or not quote.strip():
                fail(422, "exact_source_quote_required")
            r = self.db.add(
                s,
                "owner",
                "world_claim",
                {
                    "subject": subject,
                    "predicate": predicate,
                    "value": value,
                    "quote": quote,
                    "source_ids": [source_id],
                    "verification": "owner_asserted_with_quote",
                },
            )
            self.db.emit(s, "owner", "world.claim_created", {"id": r.id})
            result = view(r)
            self.remember_result(s, key, body, result)
            return result

    def world(self):
        with self.db.sessions() as s:
            claims = []
            for r in self.rows(s, "world_claim"):
                if r.status != "active":
                    continue
                d = view(r)
                source = self.get(s, d["source_ids"][0])
                d["source_eligible"] = self.source_eligible(source)
                d["source_quality"] = json.loads(source.payload).get(
                    "quality", {"rating": "unreviewed"}
                )
                claims.append(d)
            for c in claims:
                c["conflicts_with"] = [
                    x["id"]
                    for x in claims
                    if x["id"] != c["id"]
                    and x["subject"] == c["subject"]
                    and x["predicate"] == c["predicate"]
                    and x["value"] != c["value"]
                    and x["source_eligible"]
                ]
            return claims

    def grade(self, id, revision, score, feedback):
        if not feedback.strip():
            fail(422, "feedback_required")
        with self.db.tx() as s:
            r = self.get(s, id, "practice")
            d = json.loads(r.payload)
            if r.status != "active" or r.revision != revision:
                fail(409, "revision_conflict")
            for sid in d["source_ids"]:
                if not self.source_eligible(self.get(s, sid)):
                    fail(409, "source_not_eligible")
            d.update(
                evaluation="passed" if score >= 3 else "needs_practice",
                score=score,
                max_score=5,
                feedback=feedback,
                review_method="owner_rubric",
                reviewed_at=now(),
            )
            r.payload = json.dumps(d)
            r.revision += 1
            self._reconcile_course(s, d["course_id"])
            self.db.emit(
                s, "owner", "learning.practice_graded", {"id": id, "score": score}
            )
            return view(r)
