"""Tests for save_ai_quiz: empty-source guard, transaction safety, and the
structured (success, message) result contract.

The Gemini API is replaced with a stub so no external calls are made.
"""
import pytest

import quiz_service
from question_generator import QuizGenerationError
from database import get_db
from tests.conftest import make_user, create_pdf


def make_app():
    from flask import Flask
    app = Flask(__name__)
    app.secret_key = "test-secret"
    return app


def qids_for(pdf_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT id FROM quiz_questions WHERE pdf_id=? ORDER BY id",
        (pdf_id,),
    ).fetchall()
    conn.close()
    return [r["id"] for r in rows]


def insert_question(pdf_id, text="old"):
    conn = get_db()
    conn.execute(
        "INSERT INTO quiz_questions (pdf_id, question, option1, option2, option3, option4, correct_answer, explanation) "
        "VALUES (?, ?, 'a','b','c','d',0,'e')",
        (pdf_id, text),
    )
    conn.commit()
    conn.close()


@pytest.fixture
def app():
    return make_app()


def test_empty_source_is_rejected_and_keeps_questions(monkeypatch, app):
    uid = make_user("qs_empty@example.com")
    pdf_id = create_pdf(uid, text="Some study text.")

    def bomb(*a, **k):  # pragma: no cover - should not be called
        raise AssertionError("generate_questions should not run on empty text")

    monkeypatch.setattr(quiz_service, "generate_questions", bomb)
    insert_question(pdf_id, "old")
    before = qids_for(pdf_id)

    with app.test_request_context("/"):
        ok, message = quiz_service.save_ai_quiz(pdf_id, "   ")

    assert ok is False
    assert "readable study material" in message
    assert qids_for(pdf_id) == before


def test_generation_failure_preserves_questions(monkeypatch, app):
    uid = make_user("qs_fail@example.com")
    pdf_id = create_pdf(uid, text="Some study text.")
    insert_question(pdf_id, "old")

    def boom(*a, **k):
        raise QuizGenerationError("gemini_request", "nope")

    monkeypatch.setattr(quiz_service, "generate_questions", boom)
    before = qids_for(pdf_id)

    with app.test_request_context("/"):
        ok, message = quiz_service.save_ai_quiz(pdf_id, "real text")

    assert ok is False
    assert qids_for(pdf_id) == before


def test_successful_generation_replaces_questions(monkeypatch, app):
    uid = make_user("qs_ok@example.com")
    pdf_id = create_pdf(uid, text="Some study text.")
    insert_question(pdf_id, "old")

    def good(*a, **k):
        return [
            {"question": "New Q1", "options": ["a", "b", "c", "d"], "correct_answer": 1, "explanation": "why"},
            {"question": "New Q2", "options": ["w", "x", "y", "z"], "correct_answer": 3, "explanation": "why2"},
        ]

    monkeypatch.setattr(quiz_service, "generate_questions", good)

    with app.test_request_context("/"):
        ok, message = quiz_service.save_ai_quiz(pdf_id, "real text")

    assert ok is True
    conn = get_db()
    rows = conn.execute(
        "SELECT question, correct_answer FROM quiz_questions WHERE pdf_id=? ORDER BY id",
        (pdf_id,),
    ).fetchall()
    conn.close()
    assert [r["question"] for r in rows] == ["New Q1", "New Q2"]
    assert [r["correct_answer"] for r in rows] == [1, 3]


def test_insert_failure_rolls_back_transaction(monkeypatch, app):
    uid = make_user("qs_rollback@example.com")
    pdf_id = create_pdf(uid, text="Some study text.")
    insert_question(pdf_id, "keep me")

    def malformed(*a, **k):
        # Only one option -> the SQL insert will fail, so nothing must be saved.
        return [{"question": "Q", "options": ["a"], "correct_answer": 0, "explanation": "e"}]

    monkeypatch.setattr(quiz_service, "generate_questions", malformed)
    before = qids_for(pdf_id)

    with app.test_request_context("/"):
        ok, message = quiz_service.save_ai_quiz(pdf_id, "real text")

    assert ok is False
    # The DELETE must have been rolled back: the previous question remains.
    assert qids_for(pdf_id) == before