import logging

from database import get_db
from question_generator import generate_questions, QuizGenerationError

logger = logging.getLogger(__name__)


def save_ai_quiz(pdf_id, extracted_text, course=None):
    """
    Generate quiz questions using AI and save them into SQLite.

    When *course* is provided, the topic vocabulary for that course is
    passed to the generator so questions use valid topic names.

    Returns ``(success: bool, message: str)`` so the caller can flash a
    specific, user-safe error instead of a generic failure.
    """
    source = (extracted_text or "").strip()
    if not source:
        logger.warning("QUIZ_PIPELINE: pdf=%s source text is empty; aborting.", pdf_id)
        return False, (
            "Quiz generation requires readable study material. "
            "No text was extracted from this PDF."
        )

    logger.info(
        "QUIZ_PIPELINE: pdf=%s source chars=%d; generating questions.",
        pdf_id, len(source),
    )

    # Resolve course from DB if not provided
    if not course:
        conn = get_db()
        row = conn.execute(
            "SELECT course FROM uploaded_pdfs WHERE id=?", (pdf_id,)
        ).fetchone()
        conn.close()
        if row:
            course = row["course"]

    try:
        questions = generate_questions(
            source,
            session_get("question_count", 10),
            session_get("difficulty", "Medium"),
            course=course,
        )
    except QuizGenerationError as exc:
        logger.error(
            "QUIZ_PIPELINE: pdf=%s generation failed at stage '%s': %s",
            pdf_id, exc.stage, exc.message,
        )
        if exc.stage == "groq_auth":
            return False, (
                "AI service is unavailable: the server's Groq API key is "
                "invalid or expired. Please ask the administrator to set a "
                "valid GROQ_API_KEY and restart the app."
            )
        if exc.stage == "groq_connection":
            return False, (
                "AI service is unreachable from the server (network error). "
                "If hosted on PythonAnywhere's free tier, api.groq.com may "
                "not be whitelisted — otherwise check the server's internet "
                "connection and try again."
            )
        if exc.stage == "gemini_quota":
            return False, (
                "Today's free AI limit is reached (resets at midnight "
                "Pacific time). Please try generating the quiz again later."
            )
        return False, "Failed to generate AI quiz. Please try again."
    except Exception as exc:
        logger.error(
            "QUIZ_PIPELINE: pdf=%s unexpected generation failure: %r",
            pdf_id, exc,
        )
        return False, "Failed to generate AI quiz. Please try again."

    if not questions:
        return False, "Failed to generate AI quiz. No questions were produced."

    conn = get_db()
    cursor = conn.cursor()
    try:
        # Old questions are removed only after a successful generation, and the
        # delete + inserts run in a single transaction: any mid-insert failure
        # rolls back the delete so existing valid questions are never lost.
        cursor.execute(
            "DELETE FROM quiz_questions WHERE pdf_id=?",
            (pdf_id,)
        )

        for q in questions:
            cursor.execute("""
                INSERT INTO quiz_questions(
                    pdf_id, question, option1, option2, option3, option4,
                    correct_answer, explanation, topic, difficulty_level
                )
                VALUES(?,?,?,?,?,?,?,?,?,?)
            """, (
                pdf_id,
                q["question"],
                q["options"][0],
                q["options"][1],
                q["options"][2],
                q["options"][3],
                q["correct_answer"],
                q["explanation"],
                q.get("topic", "General"),
                q.get("difficulty", "Medium"),
            ))

        conn.commit()
        logger.info(
            "QUIZ_PIPELINE: pdf=%s saved %d questions.",
            pdf_id, len(questions),
        )
        return True, "AI quiz generated successfully."
    except Exception as exc:
        conn.rollback()
        logger.error(
            "QUIZ_PIPELINE: pdf=%s database insert failed (rolled back): %r",
            pdf_id, exc,
        )
        return False, "Failed to save the AI quiz. Please try again."
    finally:
        conn.close()


def session_get(key, default=None):
    """Read a Flask session value without importing flask at module top-level.

    Keeps this module importable from scripts that have no request context
    (e.g. the standalone test scripts in the project root).
    """
    from flask import session
    return session.get(key, default)