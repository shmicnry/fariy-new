"""Source-backed text file ingestion, chunk reading and evidence-based practice records."""

import base64
import binascii
import hashlib
import json
from pathlib import PurePath

from .service import Service, fail
from .store import view, now

CHUNK_SIZE = 1200


def chunks(text):
    return [
        {
            "index": i // CHUNK_SIZE,
            "start": i,
            "end": min(i + CHUNK_SIZE, len(text)),
            "text": text[i : i + CHUNK_SIZE],
        }
        for i in range(0, len(text), CHUNK_SIZE)
    ]


class LearningService(Service):
    def ingest(self, filename, encoded, key):
        if "/" in filename or "\\" in filename or not filename.strip():
            fail(422, "filename_must_be_basename")
        if PurePath(filename).suffix.lower() not in (".txt", ".md"):
            fail(415, "supported_files_txt_md_only")
        if len(encoded) > 1_400_000:
            fail(413, "file_too_large")
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            fail(422, "invalid_base64")
        if len(raw) > 1_048_576:
            fail(413, "file_too_large")
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            fail(422, "utf8_required")
        if not text.strip() or "\x00" in text or len(text) > 256000:
            fail(422, "invalid_text_file")
        # No file names or file content become executable paths or instructions.
        result = self.material(filename, text, key)
        return dict(
            result,
            file_sha256=hashlib.sha256(raw).hexdigest(),
            chunk_count=len(chunks(text)),
        )

    def practice(self, course_id, revision, answer, evidence, key):
        with self.db.tx() as s:
            body = {
                "op": "learning.practice",
                "course_id": course_id,
                "revision": revision,
                "answer": answer,
                "evidence": evidence,
            }
            cached = self.replay(s, key, body)
            if cached is not None:
                return cached
            course = self.get(s, course_id, "course")
            d = json.loads(course.payload)
            if course.status != "active" or course.revision != revision:
                fail(409, "revision_conflict")
            if d["stage"] not in ("awaiting_assessment", "needs_practice"):
                fail(409, "course_not_ready")
            if not answer.strip() or not evidence.strip():
                fail(422, "practice_evidence_required")
            for id in d["source_ids"]:
                source = self.get(s, id)
                if source.status != "active" or evidence not in json.loads(
                    source.payload
                ).get("text", ""):
                    fail(422, "exact_source_quote_required")
            row = self.db.add(
                s,
                "owner",
                "practice",
                {
                    "course_id": course_id,
                    "answer": answer,
                    "evidence_quote": evidence,
                    "source_ids": d["source_ids"] + [course.id],
                    "evaluation": "ungraded",
                    "submitted_at": now(),
                },
            )
            self.db.emit(
                s,
                "owner",
                "learning.practice_submitted",
                {"id": row.id, "course_id": course_id},
            )
            result = view(row)
            self.remember_result(s, key, body, result)
            return result
