import os
import sys
import tempfile
import pathlib

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# Redirect the app database to a temp file BEFORE the app is imported so the
# real database.db (and its real user data) is never touched by tests.
#
# NOTE: pytest imports this file twice (as `conftest` and as `tests.conftest`,
# because tests/ has no __init__.py and is treated as a namespace package).
# The guard below makes the DB isolation idempotent: the second import reuses
# the same temp DB instead of swapping in a fresh, schema-less one.
import database as _database

if getattr(_database, "_TEST_TMP_DIR", None):
    _TMP_DIR = _database._TEST_TMP_DIR
    _database.DB_PATH = os.path.join(_TMP_DIR, "test.db")
else:
    _TMP_DIR = tempfile.mkdtemp(prefix="gate_mentor_tests_")
    _database.DB_PATH = os.path.join(_TMP_DIR, "test.db")
    _database._TEST_TMP_DIR = _TMP_DIR

import pytest
import Main_page  # noqa: F401  (registers blueprints, creates schema)
from Main_page import app
from database import get_db
from auth import hash_password

app.config["TESTING"] = True

ALL_TABLES = [
    "auth_attempts",
    "guest_trials",
    "revision_schedule",
    "study_plan",
    "uploaded_pdf_pages",
    "saved_answers",
    "ai_doubt_history",
    "study_sessions",
    "recent_activity",
    "notifications",
    "question_attempts",
    "quiz_results",
    "quiz_questions",
    "uploaded_pdfs",
    "user_courses",
    "users",
]


@pytest.fixture(autouse=True)
def fresh_db():
    """Start every test with an empty database (schema is created on import)."""
    conn = get_db()
    cur = conn.cursor()
    for table in ALL_TABLES:
        cur.execute(f"DELETE FROM {table}")
    conn.commit()
    conn.close()
    yield


@pytest.fixture
def client():
    return app.test_client()


def make_user(email, name="Test User", course="GATE", paid=True):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO users (name, email, password, selected_course, payment_plan, payment_status, trial_used, trial_credits) "
        "VALUES (?, ?, ?, ?, ?, ?, 0, 1)",
        (name, email, hash_password("StrongPass123"), course, 1000, "PAID" if paid else "NOT_PAID"),
    )
    uid = cur.lastrowid
    if paid:
        cur.execute(
            "INSERT INTO user_courses (user_id, course_name, payment_plan, payment_status) VALUES (?, ?, 1000, 'PAID')",
            (uid, course),
        )
    conn.commit()
    conn.close()
    return uid


def login(client, email, uid, token):
    with client.session_transaction() as sess:
        sess["user_email"] = email
        sess["user_id"] = uid
        sess["user_name"] = "T"
        sess["_csrf_token"] = token


def set_csrf(client, token):
    with client.session_transaction() as sess:
        sess["_csrf_token"] = token


def create_pdf(uid, course="GATE", name="notes.pdf", text="Sample engineering study notes."):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO uploaded_pdfs (user_id, course, pdf_name, file_path, upload_time, pdf_type, total_pages, word_count, character_count, extracted_text, status) "
        "VALUES (?, ?, ?, ?, '2026-01-01 10:00:00', 'Digital', 1, 10, 100, ?, 'Processed')",
        (uid, course, name, name, text),
    )
    pid = cur.lastrowid
    conn.commit()
    conn.close()
    return pid


def create_question(pdf_id, correct=0):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO quiz_questions (pdf_id, question, option1, option2, option3, option4, correct_answer, explanation) "
        "VALUES (?, 'Question?', 'OptA', 'OptB', 'OptC', 'OptD', ?, 'explanation')",
        (pdf_id, correct),
    )
    qid = cur.lastrowid
    conn.commit()
    conn.close()
    return qid


def create_trial(trial_id="TRIAL_TEST", course="GATE", used=False, fingerprint=None, ip=None):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO guest_trials (trial_id, browser_token, course, pdf_credit, quiz_credit, trial_used, pdf_uploaded, quiz_generated, fingerprint, ip) "
        "VALUES (?, ?, ?, 1, 1, ?, 0, 0, ?, ?)",
        (trial_id, f"TOKEN_{trial_id}", course, 1 if used else 0, fingerprint, ip),
    )
    tid = cur.lastrowid
    conn.commit()
    conn.close()
    return tid


@pytest.fixture
def no_gemini(monkeypatch):
    """Stub the AI quiz generator so tests never call the Gemini API."""
    import ai_quiz

    calls = []

    def stub(pdf_id, extracted_text, **kwargs):
        calls.append((pdf_id, extracted_text))
        return True, "stubbed"

    monkeypatch.setattr(ai_quiz, "save_ai_quiz", stub)
    return calls
