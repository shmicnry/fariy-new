import base64
import io
import json
import zipfile
import httpx
import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
from fairy.app import create_app
from fairy.document_extract import extract, extract_pdf
from fairy.worker import tick
from tests.db import postgres_url


def pdf_bytes(text="Synthetic text"):
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject(
                {NameObject("/F1"): writer._add_object(font)}
            )
        }
    )
    stream = DecodedStreamObject()
    stream.set_data(("BT /F1 12 Tf 20 100 Td (" + text + ") Tj ET").encode())
    page[NameObject("/Contents")] = writer._add_object(stream)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def docx_bytes(xml=None):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr(
            "word/document.xml",
            xml
            or '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>植物需要水分。</w:t></w:r></w:p></w:body></w:document>',
        )
    return out.getvalue()


def test_pdf_and_docx_real_isolated_extraction():
    pdf = extract(pdf_bytes(), ".pdf")
    assert pdf["text"] == "Synthetic text"
    assert pdf["segments"][0]["label"] == "page:1"
    word = extract(docx_bytes(), ".docx")
    assert word["text"] == "植物需要水分。"
    assert word["segments"][0]["label"] == "paragraph:1"


def test_blank_pdf_requires_ocr_and_entities_rejected():
    w = PdfWriter()
    w.add_blank_page(width=300, height=300)
    data = io.BytesIO()
    w.write(data)
    with pytest.raises(ValueError, match="ocr"):
        extract(data.getvalue(), ".pdf")
    with pytest.raises(ValueError, match="entities"):
        extract(docx_bytes('<!DOCTYPE x [<!ENTITY a "boom">]><x/>'), ".docx")


def test_mixed_pdf_uses_ocr_only_for_blank_page(monkeypatch):
    source = PdfReader(io.BytesIO(pdf_bytes("Text layer")))
    writer = PdfWriter()
    writer.add_page(source.pages[0])
    writer.add_blank_page(width=300, height=300)
    output = io.BytesIO()
    writer.write(output)
    monkeypatch.setattr(
        "fairy.document_extract.ocr_pdf_pages",
        lambda _: {2: "Scanned page text."},
    )
    result = extract_pdf(output.getvalue())
    assert "Text layer" in result["text"]
    assert "Scanned page text." in result["text"]
    assert result["method"] == "text_and_pdf_ocr"
    assert result["pdf_ocr_pages"] == [2]
    assert result["ocr"] is True


def test_model_quiz_draft_requires_owner_review(tmp_path, monkeypatch):
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "done": True,
                "message": {
                    "content": json.dumps(
                        {
                            "questions": [
                                {
                                    "question": "植物需要什么？",
                                    "choices": ["水分", "火焰"],
                                    "correct_index": 0,
                                }
                            ]
                        },
                        ensure_ascii=False,
                    )
                },
            },
        )

    monkeypatch.setenv("FAIRY_OLLAMA_MODEL", "draft-fixture")
    app = create_app(
        postgres_url(tmp_path),
        token="t",
        transport=httpx.MockTransport(handler),
    )
    client = TestClient(app)
    client.headers["Authorization"] = "Bearer t"
    source = app.state.service.material(
        "draft-source",
        "植物需要水分。",
        "draft-source",
    )["material"]
    response = client.post(
        "/v2/learning/quizzes/drafts",
        json={
            "source_id": source["id"],
            "title": "模型草稿",
            "evidence": "植物需要水分。",
            "question_count": 1,
        },
        headers={"Idempotency-Key": "draft"},
    )
    assert response.status_code == 200, response.text
    draft = response.json()
    assert draft["status"] == "pending_review"
    assert draft["executable"] is False
    assert client.get("/v2/learning/quizzes").json() == []

    approved = client.post(
        "/v2/learning/quizzes/drafts/" + draft["id"] + "/approve",
        json={
            "revision": draft["revision"],
            "title": "人工确认题目",
            "questions": [
                {
                    "question": "植物需要什么？",
                    "choices": ["水分", "火焰"],
                    "correct_index": 0,
                }
            ],
        },
        headers={"Idempotency-Key": "approve-draft"},
    )
    assert approved.status_code == 200, approved.text
    quiz = approved.json()
    assert quiz["title"] == "人工确认题目"
    assert quiz["rubric"] == "owner_reviewed_model_draft"
    assert len(seen) == 1
    assert (
        next(
            item
            for item in client.get("/v2/learning/quizzes/drafts").json()
            if item["id"] == draft["id"]
        )["status"]
        == "approved"
    )


def test_model_quiz_draft_requires_exact_source_quote(tmp_path):
    app = create_app(postgres_url(tmp_path), token="t")
    client = TestClient(app)
    client.headers["Authorization"] = "Bearer t"
    source = app.state.service.material(
        "draft-source",
        "植物需要水分。",
        "draft-source",
    )["material"]
    response = client.post(
        "/v2/learning/quizzes/drafts",
        json={
            "source_id": source["id"],
            "title": "错误草稿",
            "evidence": "不存在的原文",
            "question_count": 1,
        },
        headers={"Idempotency-Key": "draft-quote"},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "exact_source_quote_required"


def test_docx_zip_expansion_refused():
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "x")
        z.writestr("word/document.xml", "x" * 4_000_001)
    with pytest.raises(ValueError, match="too_large"):
        extract(out.getvalue(), ".docx")


def test_file_upload_pdf_preserves_page_location(tmp_path):
    app = create_app(postgres_url(tmp_path), token="t")
    c = TestClient(app)
    c.headers["Authorization"] = "Bearer t"
    r = c.post(
        "/v2/learning/files",
        json={
            "filename": "paper.pdf",
            "content_base64": base64.b64encode(pdf_bytes()).decode(),
        },
        headers={"Idempotency-Key": "file"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["material"]["file_format"] == ".pdf"
    tick(app.state.db)
    parts = c.get("/v2/learning/courses/" + r.json()["course"]["id"] + "/chunks").json()
    assert parts[0]["locations"][0]["label"] == "page:1"


def setup(tmp_path, monkeypatch, handler):
    monkeypatch.setenv("FAIRY_OLLAMA_MODEL", "fixture")
    app = create_app(
        postgres_url(tmp_path),
        token="t",
        transport=httpx.MockTransport(handler),
    )
    c = TestClient(app)
    c.headers["Authorization"] = "Bearer t"
    source = app.state.service.material(
        "dataset", "The code of Cedar is VELIN.", "source"
    )["material"]
    payload = {
        "source_id": source["id"],
        "title": "合成测验",
        "evidence": "The code of Cedar is VELIN.",
        "questions": [
            {
                "question": "What is the code of Cedar?",
                "choices": ["XERON", "VELIN"],
                "correct_index": 1,
            }
        ],
    }
    r = c.post(
        "/v2/learning/quizzes", json=payload, headers={"Idempotency-Key": "quiz"}
    )
    assert r.status_code == 200, r.text
    return app, c, r.json()


def response(choice=1):
    return httpx.Response(
        200,
        json={
            "done": True,
            "message": {
                "content": json.dumps(
                    {"answers": [{"question_id": "q1", "choice": choice}]}
                )
            },
        },
    )


def test_gold_labels_not_sent_and_scoring_is_deterministic(tmp_path, monkeypatch):
    seen = []

    def handler(req):
        seen.append(json.loads(req.content))
        return response()

    app, c, quiz = setup(tmp_path, monkeypatch, handler)
    path = "/v2/learning/quizzes/" + quiz["id"] + "/runs"
    r = c.post(
        path, json={"mode": "open_book"}, headers={"Idempotency-Key": "run"}
    ).json()
    assert r["status"] == "completed" and r["correct_count"] == r["total"] == 1
    assert not r["generalization_verified"]
    assert "correct_index" not in json.dumps(seen)
    assert "source_text" in json.loads(seen[0]["messages"][1]["content"])
    again = c.post(
        path, json={"mode": "open_book"}, headers={"Idempotency-Key": "run"}
    ).json()
    assert again["id"] == r["id"] and len(seen) == 1
    assert (
        app.state.service.list("memory_proposal") == []
        and app.state.service.list("turn") == []
    )


def test_closed_book_has_no_source_text_and_wrong_answer_not_passed(
    tmp_path, monkeypatch
):
    seen = []

    def handler(req):
        seen.append(json.loads(req.content))
        return response(0)

    app, c, quiz = setup(tmp_path, monkeypatch, handler)
    r = c.post(
        "/v2/learning/quizzes/" + quiz["id"] + "/runs",
        json={"mode": "closed_book"},
        headers={"Idempotency-Key": "closed"},
    ).json()
    assert r["correct_count"] == 0
    assert "source_text" not in json.loads(seen[0]["messages"][1]["content"])


def test_deleted_source_discards_inflight_score(tmp_path, monkeypatch):
    holder = {}

    def handler(req):
        holder["app"].state.service.invalidate(holder["quiz"]["source_ids"][0], 1)
        return response()

    app, c, quiz = setup(tmp_path, monkeypatch, handler)
    holder.update(app=app, quiz=quiz)
    r = c.post(
        "/v2/learning/quizzes/" + quiz["id"] + "/runs",
        json={"mode": "open_book"},
        headers={"Idempotency-Key": "run"},
    ).json()
    assert r["status"] == "invalidated" and "correct_count" not in r


def test_duplicate_question_answers_fail(tmp_path, monkeypatch):
    def handler(req):
        return httpx.Response(
            200,
            json={
                "done": True,
                "message": {
                    "content": json.dumps(
                        {
                            "answers": [
                                {"question_id": "q1", "choice": 1},
                                {"question_id": "q1", "choice": 1},
                            ]
                        }
                    )
                },
            },
        )

    app, c, q = setup(tmp_path, monkeypatch, handler)
    r = c.post(
        "/v2/learning/quizzes/" + q["id"] + "/runs",
        json={"mode": "open_book"},
        headers={"Idempotency-Key": "bad"},
    ).json()
    assert r["status"] == "failed" and "correct_count" not in r


def test_effect_separates_current_and_invalidated_model_assessment(
    tmp_path, monkeypatch
):
    def handler(req):
        return response(1)

    app, c, quiz = setup(tmp_path, monkeypatch, handler)
    c.post(
        "/v2/learning/quizzes/" + quiz["id"] + "/runs",
        json={"mode": "open_book"},
        headers={"Idempotency-Key": "effect-run"},
    )
    course = app.state.service.list("course")[0]
    source_id = course["source_ids"][0]
    source = c.get("/v2/learning/sources").json()[0]
    before = c.get("/v2/learning/courses/" + course["id"] + "/effect").json()
    assert before["model_assessment_runs"] == 1
    assert before["invalidated_model_assessment_runs"] == 0
    assert (
        c.patch(
            "/v2/learning/sources/" + source_id,
            json={
                "revision": source["revision"],
                "rating": "disputed",
                "reason": "验证失效后的效果统计",
                "expires_at": None,
            },
        ).status_code
        == 200
    )
    after = c.get("/v2/learning/courses/" + course["id"] + "/effect").json()
    assert after["model_assessment_runs"] == 0
    assert after["invalidated_model_assessment_runs"] == 1


def test_assessment_idempotency_replay_refreshes_source_eligibility(
    tmp_path, monkeypatch
):
    def handler(req):
        return response(1)

    app, c, quiz = setup(tmp_path, monkeypatch, handler)
    path = "/v2/learning/quizzes/" + quiz["id"] + "/runs"
    first = c.post(
        path,
        json={"mode": "open_book"},
        headers={"Idempotency-Key": "stale-replay"},
    ).json()
    assert first["source_eligible"] is True
    source = c.get("/v2/learning/sources").json()[0]
    assert (
        c.patch(
            "/v2/learning/sources/" + source["id"],
            json={
                "revision": source["revision"],
                "rating": "disputed",
                "reason": "复核重放结果",
                "expires_at": None,
            },
        ).status_code
        == 200
    )
    replay = c.post(
        path,
        json={"mode": "open_book"},
        headers={"Idempotency-Key": "stale-replay"},
    ).json()
    assert replay["id"] == first["id"]
    assert replay["source_eligible"] is False


def test_boolean_model_choice_is_not_a_numeric_answer(tmp_path, monkeypatch):
    def handler(req):
        return httpx.Response(
            200,
            json={
                "done": True,
                "message": {
                    "content": json.dumps(
                        {"answers": [{"question_id": "q1", "choice": True}]}
                    )
                },
            },
        )

    app, c, q = setup(tmp_path, monkeypatch, handler)
    r = c.post(
        "/v2/learning/quizzes/" + q["id"] + "/runs",
        json={"mode": "open_book"},
        headers={"Idempotency-Key": "bool"},
    ).json()
    assert r["status"] == "failed" and "correct_count" not in r
