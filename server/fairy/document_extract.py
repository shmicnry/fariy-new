"""Bounded text extraction. Binary parsers run in a separate, credential-free process."""

import io
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile
import xml.etree.ElementTree as ET

MAX_TEXT = 256000


def join_segments(parts):
    text = ""
    segments = []
    for label, value in parts:
        if text:
            text += "\n"
        start = len(text)
        text += value
        segments.append({"label": label, "start": start, "end": len(text)})
        if len(text) > MAX_TEXT:
            raise ValueError("extracted_text_too_large")
    if not text.strip():
        raise ValueError("no_extractable_text_ocr_not_available")
    return {"text": text, "segments": segments, "method": "text_extraction_no_ocr"}


def extract_docx(raw):
    if not raw.startswith(b"PK"):
        raise ValueError("invalid_docx")
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        items = z.infolist()
        if len(items) > 2000 or sum(i.file_size for i in items) > 32_000_000:
            raise ValueError("docx_expansion_limit")
        names = [i.filename for i in items]
        if (
            len(names) != len(set(names))
            or "word/document.xml" not in names
            or "[Content_Types].xml" not in names
        ):
            raise ValueError("invalid_docx")
        if any("vbaProject" in n for n in names):
            raise ValueError("macro_documents_not_supported")
        info = z.getinfo("word/document.xml")
        if info.file_size > 4_000_000:
            raise ValueError("docx_xml_too_large")
        xml = z.read(info)
        if b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():
            raise ValueError("xml_entities_not_allowed")
        root = ET.fromstring(xml)
        ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        paragraphs = []
        for i, p in enumerate(root.iter(ns + "p"), 1):
            value = "".join(n.text or "" for n in p.iter(ns + "t"))
            if value.strip():
                paragraphs.append(("paragraph:" + str(i), value))
        return join_segments(paragraphs)


def extract_pdf(raw):
    if not raw.startswith(b"%PDF-"):
        raise ValueError("invalid_pdf")
    from pypdf import PdfReader, overwrite_configuration

    overwrite_configuration(
        zlib_maximum_output_length=8_000_000,
        lzw_maximum_output_length=8_000_000,
        run_length_maximum_output_length=8_000_000,
        stream_decoding_work_maximum_length=32_000_000,
    )

    reader = PdfReader(io.BytesIO(raw), strict=True)
    if reader.is_encrypted:
        raise ValueError("encrypted_pdf_not_supported")
    if len(reader.pages) > 100:
        raise ValueError("pdf_page_limit")
    parts = []
    for i, page in enumerate(reader.pages, 1):
        content = page.get_contents()
        if content is not None and len(content.get_data()) > 8_000_000:
            raise ValueError("pdf_content_limit")
        parts.append(("page:" + str(i), (page.extract_text() or "").strip()))
    return join_segments(parts)


def extract(raw, suffix):
    if suffix in (".txt", ".md"):
        value = raw.decode("utf-8-sig")
        if "\x00" in value:
            raise ValueError("invalid_text_file")
        return join_segments([("text", value)])
    if suffix not in (".pdf", ".docx"):
        raise ValueError("unsupported_file_format")
    # No inherited provider credentials, shell, external document resources, or output files.
    payload = json.dumps(
        {"suffix": suffix, "data": __import__("base64").b64encode(raw).decode()}
    ).encode()
    import tempfile, time
    import psutil

    with tempfile.TemporaryFile() as output:
        proc = subprocess.Popen(
            [sys.executable, "-m", "fairy.document_extract"],
            stdin=subprocess.PIPE,
            stdout=output,
            stderr=subprocess.DEVNULL,
            env={
                "PATH": os.defpath,
                "PYTHONUTF8": "1",
                "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
            },
        )
        try:
            proc.stdin.write(payload)
            proc.stdin.close()
            start = time.monotonic()
            while proc.poll() is None:
                if time.monotonic() - start > 20:
                    raise ValueError("document_parse_timeout")
                try:
                    if psutil.Process(proc.pid).memory_info().rss > 768 * 1024 * 1024:
                        raise ValueError("document_memory_limit")
                except psutil.NoSuchProcess:
                    pass
                time.sleep(0.02)
            output.seek(0)
            stdout = output.read(1_100_001)
            if proc.returncode or len(stdout) > 1_100_000:
                raise ValueError("document_parse_failed_or_resource_limit")
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait()
    data = json.loads(stdout)
    if "error" in data:
        raise ValueError(data["error"])
    return data


def main():
    import resource

    resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
    if sys.platform != "darwin":
        resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024, 768 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))
    request = json.loads(sys.stdin.buffer.read(1_500_000))
    import base64

    raw = base64.b64decode(request["data"], validate=True)
    try:
        data = extract_pdf(raw) if request["suffix"] == ".pdf" else extract_docx(raw)
    except ValueError as e:
        data = {
            "error": (
                str(e)
                if str(e)
                in (
                    "encrypted_pdf_not_supported",
                    "pdf_page_limit",
                    "pdf_content_limit",
                    "no_extractable_text_ocr_not_available",
                    "docx_expansion_limit",
                    "docx_xml_too_large",
                    "macro_documents_not_supported",
                    "xml_entities_not_allowed",
                    "extracted_text_too_large",
                )
                else "invalid_document"
            )
        }
    except Exception:
        data = {"error": "invalid_document"}
    print(json.dumps(data, ensure_ascii=False))


if __name__ == "__main__":
    main()
