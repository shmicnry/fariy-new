import base64
import io
import json
import zipfile
import httpx
import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
from fairy.app import create_app
from fairy.document_extract import extract
from fairy.worker import tick


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


def test_docx_zip_expansion_refused():
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "x")
        z.writestr("word/document.xml", "x" * 4_000_001)
    with pytest.raises(ValueError, match="too_large"):
        extract(out.getvalue(), ".docx")


def test_file_upload_pdf_preserves_page_location(tmp_path):
    app = create_app("sqlite:///" + str(tmp_path / "test.db"), token="t")
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
        "sqlite:///" + str(tmp_path / "q.db"),
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
