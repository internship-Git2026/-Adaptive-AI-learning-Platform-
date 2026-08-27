"""Route-level tests for the AI quiz generation flow.

These verify the generate route's behaviour without touching the Gemini API:
  * empty study text is rejected with a clear message and no DB writes,
  * the preview page renders for legacy PDFs that have no extracted text.
"""
from database import get_db
from tests.conftest import make_user, login, create_pdf


def _insert_pdf(uid, text):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO uploaded_pdfs (user_id, course, pdf_name, file_path, upload_time, pdf_type, total_pages, word_count, character_count, extracted_text, status) "
        "VALUES (?, 'GATE', 'empty.pdf', 'empty.pdf', '2026-01-01 10:00:00', 'OCR', 1, 0, 0, ?, 'Processed')",
        (uid, text),
    )
    pid = cur.lastrowid
    conn.commit()
    conn.close()
    return pid


def test_generate_with_empty_text_fails_cleanly(client):
    uid = make_user("emptytext@example.com")
    login(client, "emptytext@example.com", uid, "tok")
    pid = _insert_pdf(uid, "")

    # No Gemini stub needed: save_ai_quiz rejects empty source before any call.
    r = client.post(f"/ai-quiz/generate/{pid}", data={
        "csrf_token": "tok", "question_count": 10, "difficulty": "Medium", "duration": 20,
    })
    assert r.status_code == 302
    conn = get_db()
    count = conn.execute("SELECT COUNT(*) FROM quiz_questions WHERE pdf_id=?", (pid,)).fetchone()[0]
    conn.close()
    assert count == 0


def test_preview_page_renders_for_empty_text_pdf(client):
    uid = make_user("emptypreview@example.com")
    login(client, "emptypreview@example.com", uid, "tok")
    pid = _insert_pdf(uid, "")
    r = client.get(f"/pdf-upload/preview/{pid}")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "readable text could not be extracted" in body
    assert "Quiz generation requires readable study material" in body


def test_preview_page_renders_for_valid_text_pdf(client):
    uid = make_user("validpreview@example.com")
    login(client, "validpreview@example.com", uid, "tok")
    pid = create_pdf(uid, name="valid.pdf", text="Valid engineering study notes.")
    r = client.get(f"/pdf-upload/preview/{pid}")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "text extracted" in body
    assert "Generate AI Quiz" in body