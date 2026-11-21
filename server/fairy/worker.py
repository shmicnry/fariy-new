"""Durable extractive study worker with heartbeat, locking, and crash backoff."""

import argparse
import json
import os
import signal
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .store import Store, now
from .service import Service
from .autonomy import AutonomyService
from .knowledge import KnowledgeService
from .link_fetch import fetch_text
from .models import recover_stale_invocations


def status_path(state_dir):
    return Path(state_dir).resolve() / "worker-status.json"


def write_status(state_dir, payload):
    directory = Path(state_dir).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    target = status_path(directory)
    temporary = target.with_name(target.name + f".{os.getpid()}.tmp")
    encoded = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink(missing_ok=True)


def read_status(state_dir):
    target = status_path(state_dir)
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    pid = data.get("pid")
    if not isinstance(pid, int):
        data["alive"] = False
        return data
    try:
        os.kill(pid, 0)
        data["alive"] = True
    except ProcessLookupError:
        data["alive"] = False
    except PermissionError:
        data["alive"] = True
    return data


class WorkerLock:
    def __init__(self, state_dir):
        self.path = Path(state_dir).resolve() / "worker.pid"
        self.acquired = False

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                descriptor = os.open(
                    self.path,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                )
            except FileExistsError:
                try:
                    existing = int(self.path.read_text(encoding="utf-8").strip())
                except ValueError:
                    self.path.unlink(missing_ok=True)
                    continue
                except FileNotFoundError:
                    continue
                except OSError:
                    raise RuntimeError("worker_lock_unreadable")
                try:
                    os.kill(existing, 0)
                except ProcessLookupError:
                    self.path.unlink(missing_ok=True)
                    continue
                except PermissionError:
                    pass
                raise RuntimeError(f"worker_already_running pid={existing}")
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(str(os.getpid()))
            self.acquired = True
            return self
        raise RuntimeError("worker_lock_unavailable")

    def __exit__(self, *_):
        if self.acquired:
            try:
                owner = int(self.path.read_text(encoding="utf-8").strip())
            except (OSError, ValueError):
                owner = None
            if owner == os.getpid():
                self.path.unlink(missing_ok=True)


def refresh_due_source(db, autonomy, collector=fetch_text):
    service = KnowledgeService(db)
    current = datetime.now(timezone.utc)
    with db.sessions() as session:
        config = autonomy._config(session)
        if not config.get("source_refresh_enabled", False):
            return None
        daily_limit = int(config.get("source_refresh_daily_limit", 5))
        allowed_hosts = config.get("source_allowed_hosts", [])
        attempts = sum(
            autonomy._is_today(row.created_at)
            for row in service.rows(session, "source_refresh")
        )
        if daily_limit <= 0 or attempts >= daily_limit:
            return None
        sources = {
            row.id: row
            for row in service.rows(session, "material")
            if row.status == "active"
            and json.loads(row.payload).get("source_type") == "web_link"
            and service.source_host_allowed(
                json.loads(row.payload).get("url", ""),
                allowed_hosts,
            )
        }
        schedules = {
            json.loads(row.payload).get("source_id"): row
            for row in service.rows(session, "source_refresh_schedule")
            if row.status == "active"
        }
        due = None
        for source_id, source in sources.items():
            schedule = schedules.get(source_id)
            try:
                next_check = (
                    autonomy._timestamp(json.loads(schedule.payload)["next_check_at"])
                    if schedule
                    else current
                )
            except (TypeError, ValueError):
                next_check = current
            if next_check <= current and (due is None or schedule is None):
                due = (source, schedule)
        if due is None:
            return None
        source, schedule = due

    if schedule is None:
        with db.tx() as session:
            schedule = db.add(
                session,
                "owner",
                "source_refresh_schedule",
                {
                    "source_id": source.id,
                    "next_check_at": current.isoformat(),
                    "consecutive_failures": 0,
                    "last_status": "due",
                },
            )

    interval = int(config.get("source_refresh_interval_hours", 24))
    source_data = json.loads(source.payload)
    result = service.refresh_source(
        source.id,
        source.revision,
        f"auto-source-{source.id}-{source.revision}-{schedule.revision}",
        collector,
    )
    with db.tx() as session:
        schedule = service.get(session, schedule.id, "source_refresh_schedule")
        payload = json.loads(schedule.payload)
        payload.update(
            last_checked_at=current.isoformat(),
            last_status=result["status"],
            last_source_revision=source.revision,
            last_source_url=source_data["url"],
        )
        if result["status"] == "failed":
            failures = int(payload.get("consecutive_failures", 0)) + 1
            delay_hours = min(interval * (2**min(failures, 6)), 168)
            payload.update(
                consecutive_failures=failures,
                next_check_at=(current + timedelta(hours=delay_hours)).isoformat(),
                last_error=result.get("error"),
            )
        elif result["status"] == "changed":
            payload.update(
                consecutive_failures=0,
                next_check_at=None,
                replacement_source_id=result["new_source_id"],
            )
            if schedule.status != "invalidated":
                schedule.status = "invalidated"
                db.add(
                    session,
                    "owner",
                    "source_refresh_schedule",
                    {
                        "source_id": result["new_source_id"],
                        "next_check_at": (
                            current + timedelta(hours=interval)
                        ).isoformat(),
                        "consecutive_failures": 0,
                        "last_status": "version_created",
                    },
                )
        else:
            payload.update(
                consecutive_failures=0,
                next_check_at=(current + timedelta(hours=interval)).isoformat(),
            )
        schedule.revision += 1
        schedule.payload = json.dumps(payload)
        db.emit(
            session,
            "owner",
            "learning.source_auto_checked",
            {
                "source_id": source.id,
                "status": result["status"],
                "schedule_id": schedule.id,
            },
        )
    return result


def dispatch_due_reminders(db):
    """Fire reminder/anniversary cards once at their due time, independent of study budget."""
    service = Service(db)
    current = datetime.now(timezone.utc)
    fired = []
    with db.tx() as session:
        for row in service.rows(session, "card"):
            if row.status != "active":
                continue
            data = json.loads(row.payload)
            if data.get("subtype") not in ("reminder", "anniversary"):
                continue
            remind_at = data.get("remind_at")
            if not remind_at or data.get("reminded_at"):
                continue
            try:
                due = datetime.fromisoformat(remind_at)
            except (TypeError, ValueError):
                continue
            if due.tzinfo is None or due > current:
                continue
            data["reminded_at"] = current.isoformat()
            row.payload = json.dumps(data, ensure_ascii=False)
            db.emit(
                session,
                "owner",
                "card.reminder_due",
                {
                    "id": row.id,
                    "title": data.get("title", ""),
                    "remind_at": remind_at,
                },
            )
            fired.append(row.id)
    return fired


def tick(db):
    service = Service(db)
    with db.tx() as s:
        configs = service.rows(s, "config")
        if configs and json.loads(configs[0].payload).get("daily_minutes", 45) == 0:
            return False
        for job in service.rows(s, "job"):
            if job.status != "queued":
                continue
            d = json.loads(job.payload)
            course = service.get(s, d["course_id"], "course")
            if course.status != "active":
                job.status = "cancelled"
                continue
            sources = [service.get(s, x) for x in d["source_ids"]]
            if any(not service.source_eligible(x) for x in sources):
                job.status = "blocked"
                continue
            c = json.loads(course.payload)
            from .learning import chunks

            parts = chunks("\n".join(json.loads(x.payload)["text"] for x in sources))
            index = d.get("read_chunks", 0)
            part = parts[index]
            db.add(
                s,
                "owner",
                "learning_chunk",
                {
                    "course_id": course.id,
                    "source_ids": d["source_ids"] + [course.id],
                    "locations": [
                        loc
                        for source in sources
                        for loc in json.loads(source.payload)
                        .get("extraction", {})
                        .get("segments", [])
                        if loc["start"] < part["end"] and loc["end"] > part["start"]
                    ],
                    **part,
                },
            )
            index += 1
            c.update(
                read_chunks=index,
                total_chunks=len(parts),
                stage="reading" if index < len(parts) else "awaiting_assessment",
                mastered=False,
            )
            course.revision += 1
            d.update(read_chunks=index, checkpoint=index, attempts=d["attempts"] + 1)
            if index == len(parts):
                original = "\n".join(json.loads(x.payload)["text"] for x in sources)
                c.update(
                    notes=original[:4000],
                    notes_method="extractive",
                    notes_truncated=len(original) > 4000,
                    steps_verified=2,
                )
                job.status = "completed"
                d["completed_at"] = now()
                db.emit(s, "owner", "learning.awaiting_assessment", {"id": course.id})
            else:
                db.emit(
                    s,
                    "owner",
                    "learning.chunk_read",
                    {"id": course.id, "read_chunks": index, "total_chunks": len(parts)},
                )
            course.payload = json.dumps(c)
            job.payload = json.dumps(d)
            return True
    return False


def run_cycle(db, autonomy, state_dir, started_at, cycle):
    tick_ok = False
    error = None
    try:
        recovered = recover_stale_invocations(db, Service(db))
        tick_ok = tick(db)
        reminders = dispatch_due_reminders(db)
        source_result = refresh_due_source(db, autonomy)
        stopped = autonomy.enforce_budget()
        created = autonomy.refresh()
        summary = {
            "model_invocations_recovered": len(recovered),
            "tick_processed": tick_ok,
            "reminders_dispatched": len(reminders),
            "autonomy_candidates_created": len(created),
            "autonomy_goals_stopped": len(stopped),
            "source_refresh_status": (
                source_result["status"] if source_result is not None else None
            ),
        }
    except Exception as exc:
        summary = {
            "model_invocations_recovered": 0,
            "tick_processed": False,
            "reminders_dispatched": 0,
            "autonomy_candidates_created": 0,
            "autonomy_goals_stopped": 0,
            "source_refresh_status": None,
        }
        error = type(exc).__name__
    write_status(
        state_dir,
        {
            "pid": os.getpid(),
            "started_at": started_at,
            "heartbeat_at": now(),
            "cycle": cycle,
            "status": "degraded" if error else "running",
            "error": error,
            **summary,
        },
    )
    return error is None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--state-dir")
    args = parser.parse_args()
    state_dir = args.state_dir or os.getenv("FAIRY_STATE_DIR", "var")
    if args.status:
        status = read_status(state_dir)
        if status is None:
            print(json.dumps({"status": "missing", "alive": False}))
            return 1
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return 0 if status.get("alive") else 1
    if args.interval <= 0:
        parser.error("--interval must be greater than zero")

    database_url = os.getenv("FAIRY_DATABASE_URL")
    if not database_url:
        parser.error("FAIRY_DATABASE_URL is required")
    db = Store(database_url)
    autonomy = AutonomyService(db)
    started_at = now()
    stopping = False

    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    with WorkerLock(state_dir):
        cycle = 0
        failures = 0
        while not stopping:
            cycle += 1
            healthy = run_cycle(db, autonomy, state_dir, started_at, cycle)
            if args.once:
                break
            failures = 0 if healthy else min(failures + 1, 5)
            delay = min(args.interval * (2**failures), 60)
            deadline = time.monotonic() + delay
            while not stopping and time.monotonic() < deadline:
                time.sleep(min(0.25, deadline - time.monotonic()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
