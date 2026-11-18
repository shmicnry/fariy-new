"""Deterministic autonomy queue and budget ledger; no external browsing or generation."""

from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .service import Service, fail
from .store import view


class AutonomyService(Service):
    @staticmethod
    def _timezone():
        configured = os.getenv("FAIRY_DAY_TIMEZONE", "").strip()
        if configured:
            try:
                return ZoneInfo(configured)
            except (KeyError, ValueError):
                pass
        return datetime.now().astimezone().tzinfo or timezone.utc

    @classmethod
    def _today(cls):
        return datetime.now(cls._timezone()).date()

    @staticmethod
    def _timestamp(value):
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @classmethod
    def _is_today(cls, value):
        if not value:
            return False
        try:
            return cls._timestamp(value).astimezone(
                cls._timezone()
            ).date() == cls._today()
        except (TypeError, ValueError):
            return False

    @classmethod
    def _elapsed_seconds(cls, record, data, reference=None):
        seconds = max(0, int(data.get("spent_seconds", 0)))
        if record.status == "active" and data.get("active_since"):
            current = reference or datetime.now(timezone.utc)
            try:
                seconds += max(
                    0,
                    int(
                        (
                            current - cls._timestamp(data["active_since"])
                        ).total_seconds()
                    ),
                )
            except (TypeError, ValueError):
                pass
        reserved = max(
            0,
            int(
                data.get(
                    "reserved_minutes",
                    data.get("estimated_minutes", 0),
                )
            ),
        )
        return min(seconds, reserved * 60) if reserved else seconds

    @classmethod
    def _summary_view(cls, record):
        data = json.loads(record.payload)
        elapsed = cls._elapsed_seconds(record, data)
        return {
            "spent_seconds": elapsed,
            "actual_minutes": math.ceil(elapsed / 60),
        }

    def _settle(self, record):
        data = json.loads(record.payload)
        data["spent_seconds"] = self._elapsed_seconds(record, data)
        data["active_since"] = None
        record.revision += 1
        return data

    def _config(self, session):
        rows = [row for row in self.rows(session, "config") if row.status == "active"]
        if not rows:
            return {}
        return json.loads(rows[0].payload)

    def _goal_rows(self, session):
        return [
            row
            for row in self.rows(session, "goal")
            if row.status not in ("deleted", "invalidated")
        ]

    def _usage(self, session):
        accepted = [
            row
            for row in self.rows(session, "autonomy_candidate")
            if json.loads(row.payload).get("status") == "accepted"
            and self._is_today(json.loads(row.payload).get("accepted_at"))
        ]
        used_seconds = 0
        reserved_seconds = 0
        for goal in self._goal_rows(session):
            data = json.loads(goal.payload)
            spent = self._elapsed_seconds(goal, data)
            is_open = goal.status in ("planned", "active", "paused")
            finished_today = self._is_today(
                data.get("completed_at") or data.get("cancelled_at")
            )
            if not is_open and not finished_today:
                continue
            used_seconds += spent
            if is_open:
                reserved = max(
                    0,
                    int(
                        data.get(
                            "reserved_minutes",
                            data.get("estimated_minutes", 0),
                        )
                    ),
                ) * 60
                held = max(0, reserved - spent)
                used_seconds += held
                reserved_seconds += held
        return used_seconds, reserved_seconds, len(accepted)

    def validate_config(self, data):
        if not data.get("autonomy_enabled", False):
            return
        with self.db.sessions() as session:
            used_seconds, _, _ = self._usage(session)
        if used_seconds > int(data.get("autonomy_daily_minutes", 30)) * 60:
            fail(409, "autonomy_budget_below_committed_usage")

    def budget(self):
        with self.db.sessions() as session:
            config = self._config(session)
            day = self._today()
            if not config.get("autonomy_enabled", False):
                return {
                    "enabled": False,
                    "daily_minutes": config.get("autonomy_daily_minutes", 30),
                    "used_minutes": 0,
                    "used_seconds": 0,
                    "reserved_seconds": 0,
                    "remaining_minutes": 0,
                    "remaining_seconds": 0,
                    "daily_items": config.get("autonomy_daily_items", 10),
                    "used_items": 0,
                    "remaining_items": 0,
                    "timezone": str(self._timezone()),
                    "day": day.isoformat(),
                }
            used_seconds, reserved_seconds, accepted_count = self._usage(session)
            daily_minutes = config.get("autonomy_daily_minutes", 30)
            daily_items = config.get("autonomy_daily_items", 10)
            daily_seconds = daily_minutes * 60
            return {
                "enabled": True,
                "daily_minutes": daily_minutes,
                "used_minutes": math.ceil(used_seconds / 60),
                "used_seconds": used_seconds,
                "reserved_seconds": reserved_seconds,
                "remaining_minutes": max(
                    0, math.ceil((daily_seconds - used_seconds) / 60)
                ),
                "remaining_seconds": max(0, daily_seconds - used_seconds),
                "daily_items": daily_items,
                "used_items": accepted_count,
                "remaining_items": max(0, daily_items - accepted_count),
                "timezone": str(self._timezone()),
                "day": day.isoformat(),
            }

    def goals(self):
        with self.db.sessions() as session:
            rows = []
            for goal in reversed(self._goal_rows(session)):
                rows.append(dict(view(goal), **self._summary_view(goal)))
            return rows

    def enforce_budget(self):
        now = datetime.now(timezone.utc)
        stopped = []
        with self.db.tx() as session:
            for goal in self._goal_rows(session):
                if goal.status != "active":
                    continue
                data = json.loads(goal.payload)
                reserved = max(
                    0,
                    int(
                        data.get(
                            "reserved_minutes",
                            data.get("estimated_minutes", 0),
                        )
                    ),
                )
                if self._elapsed_seconds(goal, data, now) < reserved * 60:
                    continue
                data["spent_seconds"] = reserved * 60
                data.update(
                    active_since=None,
                    pause_reason="budget_exhausted",
                    paused_at=now.isoformat(),
                )
                goal.status = "paused"
                goal.revision += 1
                goal.payload = json.dumps(data)
                stopped.append(goal.id)
                self.db.emit(
                    session,
                    "owner",
                    "autonomy.goal_paused",
                    {
                        "id": goal.id,
                        "reason": "budget_exhausted",
                    },
                )
        return stopped

    def _goal(self, session, id, revision):
        goal = self.get(session, id, "goal")
        if goal.status in ("deleted", "invalidated") or goal.revision != revision:
            fail(409, "goal_revision_conflict")
        return goal

    def start(self, id, revision):
        with self.db.tx() as session:
            goal = self._goal(session, id, revision)
            if goal.status not in ("planned", "paused"):
                fail(409, "goal_not_startable")
            data = json.loads(goal.payload)
            reserved = max(
                0,
                int(
                    data.get(
                        "reserved_minutes",
                        data.get("estimated_minutes", 0),
                    )
                ),
            )
            if reserved and self._elapsed_seconds(goal, data) >= reserved * 60:
                fail(409, "goal_budget_exhausted")
            data.update(
                active_since=datetime.now(timezone.utc).isoformat(),
                started_at=data.get("started_at")
                or datetime.now(timezone.utc).isoformat(),
                pause_reason=None,
            )
            goal.status = "active"
            goal.revision += 1
            goal.payload = json.dumps(data)
            self.db.emit(
                session,
                "owner",
                "autonomy.goal_started",
                {"id": goal.id},
            )
            return dict(view(goal), **self._summary_view(goal))

    def pause(self, id, revision):
        with self.db.tx() as session:
            goal = self._goal(session, id, revision)
            if goal.status != "active":
                fail(409, "goal_not_active")
            data = self._settle(goal)
            data.update(
                paused_at=datetime.now(timezone.utc).isoformat(),
                pause_reason="owner_paused",
            )
            goal.status = "paused"
            goal.payload = json.dumps(data)
            self.db.emit(
                session,
                "owner",
                "autonomy.goal_paused",
                {"id": goal.id, "reason": "owner_paused"},
            )
            return dict(view(goal), **self._summary_view(goal))

    def complete(self, id, revision, summary):
        if not summary.strip():
            fail(422, "goal_summary_required")
        with self.db.tx() as session:
            goal = self._goal(session, id, revision)
            if goal.status not in ("active", "paused"):
                fail(409, "goal_not_completable")
            data = self._settle(goal)
            data.update(
                summary=summary,
                completed_at=datetime.now(timezone.utc).isoformat(),
                verification="owner_reported",
            )
            goal.status = "completed"
            goal.payload = json.dumps(data)
            self.db.emit(
                session,
                "owner",
                "autonomy.goal_completed",
                {"id": goal.id},
            )
            return dict(view(goal), **self._summary_view(goal))

    def cancel(self, id, revision):
        with self.db.tx() as session:
            goal = self._goal(session, id, revision)
            if goal.status not in ("planned", "active", "paused"):
                fail(409, "goal_not_cancellable")
            if goal.status == "active":
                data = self._settle(goal)
            else:
                data = json.loads(goal.payload)
                goal.revision += 1
            data.update(
                cancelled_at=datetime.now(timezone.utc).isoformat(),
                cancellation_reason="owner_cancelled",
            )
            goal.status = "cancelled"
            goal.payload = json.dumps(data)
            self.db.emit(
                session,
                "owner",
                "autonomy.goal_cancelled",
                {"id": goal.id},
            )
            return dict(view(goal), **self._summary_view(goal))

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
                    "reserved_minutes": data["estimated_minutes"],
                    "spent_seconds": 0,
                    "active_since": None,
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
