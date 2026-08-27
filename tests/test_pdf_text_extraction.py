"""Integration tests for the shared PDF text extraction pipeline.

These run against the two real PDF fixtures shipped with the project:
  * a digital GATE PDF (embedded text layer)
  * a scanned slide-deck PDF (embedded raster image on very large pages)

They are skipped when the fixture files are not present so the suite still
runs on a fresh checkout. The OCR test is intentionally slower.
"""
import os
import io
from pathlib import Path

import pytest

from pdf_text_extraction import extract_pdf_pages, clean_text, ExtractionError
from database import get_db
from Main_page import app
from tests.conftest import make_user, login

UPLOADS = Path(__file__).resolve().parents[1] / "uploads"

DIGITAL_PDF = UPLOADS / "20260814140613_Smart-India-Hackathon_PROBLEM-STATEMENTS.pdf"
SCANNED_PDF = UPLOADS / "20260814142217_Sodium_Bicarbonate_Uses-08-08-2026-2111.pdf"


def _joined_text(pages):
    return clean_text("\n".join(text for _, text in pages))


def test_clean_text_strips_page_numbers():
    raw = "Page 1\n\nPhotosynthesis is a process.\n1 of 10\n\nMore content.\n"
    cleaned = clean_text(raw)
    assert "Page 1" not in cleaned
    assert "1 of 10" not in cleaned
    assert "Photosynthesis" in cleaned


@pytest.mark.skipif(not DIGITAL_PDF.is_file(), reason="digital fixture PDF missing")
def test_digital_pdf_extraction():
    method, pages, total = extract_pdf_pages(DIGITAL_PDF)
    joined = _joined_text(pages)
    assert method == "Digital"
    assert total == 8
    assert len(joined) > 10000
    assert len(joined.split()) > 2000


@pytest.mark.skipif(not SCANNED_PDF.is_file(), reason="scanned fixture PDF missing")
def test_scanned_pdf_ocr_extraction():
    method, pages, total = extract_pdf_pages(SCANNED_PDF)
    joined = _joined_text(pages)
    assert method == "OCR"
    assert total == 15
    # OCR must yield usable text (previously returned 0 words).
    assert len(joined.strip()) > 0
    assert len(joined.split()) > 50


def test_extract_pdf_pages_missing_file_raises(tmp_path):
    missing = tmp_path / "does-not-exist.pdf"
    with pytest.raises(Exception):
        extract_pdf_pages(missing)


@pytest.mark.skipif(not SCANNED_PDF.is_file(), reason="scanned fixture PDF missing")
def test_upload_scanned_pdf_runs_ocr_end_to_end(client, monkeypatch, tmp_path):
    """Upload the real scanned PDF through the app; OCR text must be stored."""
    import question_generator
    import doubt_solver

    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir(exist_ok=True)
    original = app.config["UPLOAD_FOLDER"]
    app.config["UPLOAD_FOLDER"] = str(upload_dir)
    try:
        uid = make_user("scan_upload@example.com", course="NEET")
        login(client, "scan_upload@example.com", uid, "tok")
        monkeypatch.setattr(question_generator, "validate_pdf_content", lambda text, course: (True, ""))
        monkeypatch.setattr(doubt_solver, "get_embedding", lambda text, is_query=False: None)

        with open(SCANNED_PDF, "rb") as fh:
            data = fh.read()

        r = client.post(
            "/pdf-upload/upload?course=NEET",
            data={
                "file": (io.BytesIO(data), "scanned.pdf"),
                "csrf_token": "tok",
            },
            content_type="multipart/form-data",
        )
        assert r.status_code == 200
        body = r.get_data(as_text=True)
        assert "OCR completed" in body

        conn = get_db()
        row = conn.execute(
            "SELECT pdf_type, total_pages, word_count, character_count, extracted_text "
            "FROM uploaded_pdfs WHERE user_id=?",
            (uid,),
        ).fetchone()
        conn.close()
        assert row is not None
        assert row["pdf_type"] == "OCR"
        assert row["total_pages"] == 15
        assert row["word_count"] > 0
        assert row["character_count"] > 0
        assert row["extracted_text"].strip()
    finally:
        app.config["UPLOAD_FOLDER"] = original