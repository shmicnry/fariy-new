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
        if PurePath(filename).suffix.lower() not in (
            ".txt",
            ".md",
            ".pdf",
            ".docx",
            ".png",
            ".jpg",
            ".jpeg",
            ".heic",
            ".tiff",
        ):
            fail(415, "supported_document_or_image_files_only")
        if len(encoded) > 1_400_000:
            fail(413, "file_too_large")
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            fail(422, "invalid_base64")
        if len(raw) > 1_048_576:
            fail(413, "file_too_large")
        from .document_extract import extract

        try:
            extraction = extract(raw, PurePath(filename).suffix.lower())
            text = extraction["text"]
        except (ValueError, UnicodeDecodeError) as error:
            code = (
                str(error)
                if isinstance(error, ValueError)
                and str(error).isascii()
                and len(str(error)) < 100
                else "document_extraction_failed"
            )
            fail(422, code)
        # No file names or file content become executable paths or instructions.
        result = self.material(
            filename,
            text,
            key,
            request_body={
                "op": "file.ingest",
                "filename": filename,
                "content_base64": encoded,
            },
        )
        with self.db.tx() as s:
            source = self.get(s, result["material"]["id"], "material")
            if source.status == "active":
                d = json.loads(source.payload)
                if "extraction" not in d:
                    d.update(
                        file_sha256=hashlib.sha256(raw).hexdigest(),
                        file_format=PurePath(filename).suffix.lower(),
                        extraction={k: v for k, v in extraction.items() if k != "text"},
                    )
                    source.payload = json.dumps(d)
            result["material"] = view(source)
            course = self.get(s, result["course"]["id"], "course")
            d = json.loads(course.payload)
            if course.status == "active" and not d.get("practice_required"):
                d["practice_required"] = True
                course.payload = json.dumps(d)
                course.revision += 1
            result["course"] = view(course)
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
                if not self.source_eligible(source) or evidence not in json.loads(
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
