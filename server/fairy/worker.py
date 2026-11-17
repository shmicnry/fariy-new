"""Durable extractive study worker. No fabricated mastery or model-based self-grading."""

import argparse
import json
import os
import time
from datetime import datetime, timezone, timedelta
from .store import Store, now
from .service import Service
from .autonomy import AutonomyService


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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    db = Store(os.getenv("FAIRY_DATABASE_URL", "sqlite:///var/fairy.db"))
    autonomy = AutonomyService(db)
    while True:
        tick(db)
        autonomy.refresh()
        if args.once:
            break
        time.sleep(2)


if __name__ == "__main__":
    main()
