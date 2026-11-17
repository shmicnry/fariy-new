"""Durable extractive study worker with heartbeat, locking, and crash backoff."""

import argparse
import json
import os
import signal
import sys
import time
from pathlib import Path

from .store import Store, now
from .service import Service
from .autonomy import AutonomyService


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
        tick_ok = tick(db)
        created = autonomy.refresh()
        summary = {"tick_processed": tick_ok, "autonomy_candidates_created": len(created)}
    except Exception as exc:
        summary = {"tick_processed": False, "autonomy_candidates_created": 0}
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

    db = Store(os.getenv("FAIRY_DATABASE_URL", "sqlite:///var/fairy.db"))
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
