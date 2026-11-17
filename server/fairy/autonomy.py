"""Deterministic autonomy queue and budget ledger; no external browsing or generation."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from .service import Service, fail
from .store import view


class AutonomyService(Service):
    def _config(self, session):
        rows = [row for row in self.rows(session, "config") if row.status == "active"]
        if not rows:
            return {}
        return json.loads(rows[0].payload)

    def budget(self):
        with self.db.sessions() as session:
            config = self._config(session)
            if not config.get("autonomy_enabled", False):
                return {
                    "enabled": False,
                    "daily_minutes": config.get("autonomy_daily_minutes", 30),
                    "used_minutes": 0,
                    "remaining_minutes": 0,
                    "daily_items": config.get("autonomy_daily_items", 10),
                    "used_items": 0,
                    "remaining_items": 0,
                }
            today = datetime.now(timezone.utc).date().isoformat()
            accepted = [
                row
                for row in self.rows(session, "autonomy_candidate")
                if json.loads(row.payload).get("status") == "accepted"
                and json.loads(row.payload).get("accepted_at", "").startswith(today)
            ]
            used_minutes = sum(
                json.loads(row.payload).get("estimated_minutes", 0) for row in accepted
            )
            daily_minutes = config.get("autonomy_daily_minutes", 30)
            daily_items = config.get("autonomy_daily_items", 10)
            return {
                "enabled": True,
                "daily_minutes": daily_minutes,
                "used_minutes": used_minutes,
                "remaining_minutes": max(0, daily_minutes - used_minutes),
                "daily_items": daily_items,
                "used_items": len(accepted),
                "remaining_items": max(0, daily_items - len(accepted)),
            }

    def refresh(self):
        created = []
        with self.db.tx() as session:
            existing = {
                json.loads(row.payload).get("dedupe_key")
                for row in self.rows(session, "autonomy_candidate")
                if row.status == "active"
            }
            for course in self.rows(session, "course"):
                data = json.loads(course.payload)
                if course.status != "active" or data.get("stage") != "needs_practice":
                    continue
                key = "course:" + course.id
                if key in existing:
                    continue
                candidate = self.db.add(
                    session,
                    "owner",
                    "autonomy_candidate",
                    {
                        "type": "learning",
                        "status": "proposed",
                        "dedupe_key": key,
                        "title": "继续练习：" + data["title"],
                        "reason": "最近练习未通过或来源需要重新验证",
                        "question": data.get("assessment", {}).get(
                            "evidence", "请补充新的练习与原文依据"
                        ),
                        "estimated_minutes": 15,
                        "source_ids": data["source_ids"] + [course.id],
                        "origin": "learning_gap",
                    },
                )
                existing.add(key)
                created.append(view(candidate))
                self.db.emit(
                    session,
                    "owner",
                    "autonomy.candidate_created",
                    {"id": candidate.id, "type": "learning"},
                )
            # Conflict candidates are derived from active, eligible claims.
            claims = []
            for claim in self.rows(session, "world_claim"):
                if claim.status != "active":
                    continue
                data = json.loads(claim.payload)
                source = self.get(session, data["source_ids"][0])
                if self.source_eligible(source):
                    claims.append((claim, data))
            for claim, data in claims:
                conflicts = [
                    other
                    for other, other_data in claims
                    if other.id != claim.id
                    and other_data["subject"] == data["subject"]
                    and other_data["predicate"] == data["predicate"]
                    and other_data["value"] != data["value"]
                    and set(other_data["source_ids"]).isdisjoint(
                        set(data["source_ids"])
                    )
                ]
                if not conflicts:
                    continue
                ids = sorted([claim.id] + [other.id for other in conflicts])
                key = "conflict:" + ":".join(ids)
                if key in existing:
                    continue
                candidate = self.db.add(
                    session,
                    "owner",
                    "autonomy_candidate",
                    {
                        "type": "world_conflict",
                        "status": "proposed",
                        "dedupe_key": key,
                        "title": "核对冲突："
                        + data["subject"]
                        + "/"
                        + data["predicate"],
                        "reason": "存在来源不同的相反主张",
                        "question": "请复核各来源，并把未解决的分歧保留为不确定性",
                        "estimated_minutes": 20,
                        "source_ids": ids,
                        "origin": "world_conflict",
                    },
                )
                existing.add(key)
                created.append(view(candidate))
                self.db.emit(
                    session,
                    "owner",
                    "autonomy.candidate_created",
                    {"id": candidate.id, "type": "world_conflict"},
                )
        return created

    def accept(self, candidate_id, revision):
        with self.db.tx() as session:
            row = self.get(session, candidate_id, "autonomy_candidate")
            data = json.loads(row.payload)
            if row.status != "active" or row.revision != revision:
                fail(409, "candidate_already_changed")
            if data["status"] != "proposed":
                fail(409, "candidate_not_proposed")
            config = self._config(session)
            if not config.get("autonomy_enabled", False):
                fail(409, "autonomy_disabled")
            budget = self.budget()
            if (
                data["estimated_minutes"] > budget["remaining_minutes"]
                or budget["remaining_items"] <= 0
            ):
                fail(409, "autonomy_budget_exhausted")
            data["status"] = "accepted"
            data["accepted_at"] = datetime.now(timezone.utc).isoformat()
            row.payload = json.dumps(data)
            row.revision += 1
            goal = self.db.add(
                session,
                "owner",
                "goal",
                {
                    "candidate_id": candidate_id,
                    "title": data["title"],
                    "reason": data["reason"],
                    "success_condition": "完成有来源的学习或冲突核对，并记录验证结果",
                    "estimated_minutes": data["estimated_minutes"],
                    "source_ids": data["source_ids"],
                },
                "planned",
            )
            self.db.emit(
                session,
                "owner",
                "autonomy.candidate_accepted",
                {"id": candidate_id, "goal_id": goal.id},
            )
            return {"candidate": view(row), "goal": view(goal), "budget": self.budget()}

    def dismiss(self, candidate_id, revision):
        with self.db.tx() as session:
            row = self.get(session, candidate_id, "autonomy_candidate")
            data = json.loads(row.payload)
            if row.status != "active" or row.revision != revision:
                fail(409, "candidate_already_changed")
            if data["status"] != "proposed":
                fail(409, "candidate_not_proposed")
            data["status"] = "dismissed"
            row.payload = json.dumps(data)
            row.revision += 1
            self.db.emit(
                session,
                "owner",
                "autonomy.candidate_dismissed",
                {"id": candidate_id},
            )
            return view(row)
