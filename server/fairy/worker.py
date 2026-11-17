"""Durable extractive study worker. No fabricated mastery or model-based self-grading."""

import argparse
import json
import os
import time
from datetime import datetime, timezone, timedelta
from .store import Store, now
from .service import Service


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
            if any(x.status != "active" for x in sources):
                job.status = "cancelled"
                continue
            c = json.loads(course.payload)
            # Bounded local extraction is a durable reading checkpoint, not proof of learning.
            c.update(
                notes="\n".join(json.loads(x.payload)["text"][:4000] for x in sources),
                notes_method="extractive",
                notes_truncated=any(
                    len(json.loads(x.payload)["text"]) > 4000 for x in sources
                ),
                stage="awaiting_assessment",
                steps_verified=2,
                mastered=False,
            )
            course.payload = json.dumps(c)
            course.revision += 1
            job.status = "completed"
            d.update(checkpoint=2, attempts=d["attempts"] + 1, completed_at=now())
            job.payload = json.dumps(d)
            db.emit(s, "owner", "learning.awaiting_assessment", {"id": course.id})
            return True
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    db = Store(os.getenv("FAIRY_DATABASE_URL", "sqlite:///var/fairy.db"))
    while True:
        tick(db)
        if args.once:
            break
        time.sleep(2)


if __name__ == "__main__":
    main()
