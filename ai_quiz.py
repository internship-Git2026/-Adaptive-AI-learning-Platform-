from flask import Blueprint, render_template, redirect, url_for, flash, request
from database import get_db
from quiz_service import save_ai_quiz
from flask import session
from quiz_activity import save_quiz_result
from course_access import has_course_access
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

ai_quiz_bp = Blueprint(
    "ai_quiz",
    __name__,
    url_prefix="/ai-quiz"
)

# ==========================================
# ACCESS CONTROL HELPERS
# ==========================================

def _current_user():
    """Return the logged-in user row, or None."""
    user_email = session.get("user_email")
    if not user_email:
        return None
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE email = ?", (user_email,))
    user = cursor.fetchone()
    conn.close()
    return user


def authorized_quiz_context(pdf_id):
    """Return (user, pdf) if the current user owns the PDF and is entitled.

    Returns (None, None, error_message) otherwise.
    """
    user = _current_user()
    if not user:
        return None, None, "Please sign in first."

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM uploaded_pdfs WHERE id = ? AND user_id = ?",
        (pdf_id, user['id']),
    )
    pdf = cursor.fetchone()
    conn.close()

    if not pdf:
        return None, None, "PDF not found or access denied."

    if user['payment_status'] != 'PAID':
        return None, None, "Please purchase a course plan to access AI quizzes."

    if not has_course_access(user['id'], pdf['course']):
        return None, None, f"You are not enrolled in the {pdf['course']} course."

    return user, pdf, None


def authorized_question_context(question_id):
    """Return (user, question) if the current user owns the parent PDF.

    Returns (None, None, error_message) otherwise.
    """
    user = _current_user()
    if not user:
        return None, None, "Please sign in first."

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT q.*, p.course AS pdf_course
        FROM quiz_questions q
        JOIN uploaded_pdfs p ON q.pdf_id = p.id
        WHERE q.id = ? AND p.user_id = ?
        """,
        (question_id, user['id']),
    )
    question = cursor.fetchone()
    conn.close()

    if not question:
        return None, None, "Question not found or access denied."

    if user['payment_status'] != 'PAID':
        return None, None, "Please purchase a course plan to access AI quizzes."

    if not has_course_access(user['id'], question['pdf_course']):
        return None, None, f"You are not enrolled in the {question['pdf_course']} course."

    return user, question, None


def _deny_quiz_access(error):
    flash(error, "warning")
    if not session.get("user_email"):
        return redirect(url_for("signin.signin_page"))
    return redirect(url_for("my_courses.my_courses_page"))

# ==========================================
# QUIZ SETTINGS PAGE
# ==========================================

@ai_quiz_bp.route("/settings/<int:pdf_id>")
def quiz_settings(pdf_id):

    user, pdf, error = authorized_quiz_context(pdf_id)
    if error:
        return _deny_quiz_access(error)

    return render_template(
        "quiz_settings.html",
        pdf_id=pdf_id,
        course_name=pdf["course"]
    )

# ==========================================
# Generate AI Quiz from Uploaded PDF
# ==========================================
@ai_quiz_bp.route("/generate/<int:pdf_id>", methods=["POST"])
def generate_quiz(pdf_id):

    user, pdf, error = authorized_quiz_context(pdf_id)
    if error:
        return _deny_quiz_access(error)

    # Server-side guard against rapid duplicate generation requests. The value
    # is a short-lived "generating" marker; it is cleared in a finally block.
    generating_until = session.get("quiz_generating_until")
    if generating_until:
        try:
            lock_end = datetime.fromisoformat(generating_until)
        except ValueError:
            lock_end = None
        if lock_end and lock_end > datetime.now():
            flash("Quiz generation is already in progress. Please wait.", "warning")
            return redirect(url_for("pdf_upload.preview_file", pdf_id=pdf_id))
    session["quiz_generating_until"] = (
        datetime.now() + timedelta(seconds=120)
    ).isoformat()

    try:
        try:
            question_count = int(request.form.get("question_count", 10))
        except (TypeError, ValueError):
            question_count = 10
        question_count = max(1, min(question_count, 50))

        difficulty = request.form.get("difficulty", "Medium")

        try:
            duration_minutes = int(request.form.get("duration", 20))
        except (TypeError, ValueError):
            duration_minutes = 20

        session["question_count"] = question_count
        session["difficulty"] = difficulty
        session["quiz_duration_minutes"] = duration_minutes
        session["quiz_duration"] = duration_minutes * 60

        source_chars = len((pdf["extracted_text"] or "").strip())
        logger.info(
            "QUIZ_PIPELINE: pdf=%s user=%s source_chars=%d count=%d difficulty=%s "
            "duration=%d route=generate start",
            pdf_id, user["id"], source_chars, question_count, difficulty,
            duration_minutes,
        )

        success, message = save_ai_quiz(
            pdf_id,
            pdf["extracted_text"],
            course=pdf["course"],
        )

        if not success:
            logger.info("QUIZ_PIPELINE: pdf=%s route=generate failed: %s", pdf_id, message)
            flash(message, "error")
            return redirect(
                url_for(
                    "pdf_upload.preview_file",
                    pdf_id=pdf_id
                )
            )

        logger.info("QUIZ_PIPELINE: pdf=%s route=generate success -> start_quiz", pdf_id)
        return redirect(
            url_for(
                "ai_quiz.start_quiz",
                pdf_id=pdf_id
            )
        )
    finally:
        session.pop("quiz_generating_until", None)


# ==========================================
# Start Quiz
# ==========================================
@ai_quiz_bp.route("/start/<int:pdf_id>")
def start_quiz(pdf_id):

    user, pdf, error = authorized_quiz_context(pdf_id)
    if error:
        return _deny_quiz_access(error)

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT *
        FROM quiz_questions
        WHERE pdf_id=?
        ORDER BY id
    """, (pdf_id,))

    questions = cursor.fetchall()

    if not questions:
        conn.close()
        flash("No quiz questions found.")
        return redirect(
            url_for(
                "pdf_upload.preview_file",
                pdf_id=pdf_id
            )
        )

    question = questions[0]

    session["score"] = 0
    session["total_questions"] = len(questions)
    session["quiz_answered"] = []
    session["quiz_completed"] = False
    session["quiz_start_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Start timer using user-selected duration
    duration_minutes = session.get("quiz_duration_minutes", 20)
    end_time = datetime.now() + timedelta(minutes=duration_minutes)
    session["quiz_end_time"] = end_time.strftime("%Y-%m-%d %H:%M:%S")

    course_name = pdf["course"]

    conn.close()
    
    end_time = datetime.strptime(
        session["quiz_end_time"],
        "%Y-%m-%d %H:%M:%S"
    )

    remaining_seconds = max(
        int((end_time - datetime.now()).total_seconds()),
        0
    )

    return render_template(
    "ai_quiz.html",
    question=question,
    question_no=1,
    total_questions=len(questions),
    pdf_id=pdf_id,
    course_name=course_name,
    timer=remaining_seconds,
)


# ==========================================
# Submit Answer
# ==========================================
@ai_quiz_bp.route("/submit/<int:question_id>", methods=["POST"])
def submit_answer(question_id):

    user, question, error = authorized_question_context(question_id)
    if error:
        return _deny_quiz_access(error)

    try:
        selected_answer = int(request.form["answer"])
    except (KeyError, TypeError, ValueError):
        flash("Invalid answer submitted.")
        return redirect(url_for("my_courses.my_courses_page"))

    conn = get_db()
    cursor = conn.cursor()

    # Total Questions
    cursor.execute("""
        SELECT COUNT(*)
        FROM quiz_questions
        WHERE pdf_id=?
    """, (question["pdf_id"],))

    total_questions = cursor.fetchone()[0]

    # Current Question Number
    cursor.execute("""
        SELECT COUNT(*)
        FROM quiz_questions
        WHERE pdf_id=?
        AND id<=?
    """, (question["pdf_id"], question_id))

    question_no = cursor.fetchone()[0]

    # Next Question
    cursor.execute("""
        SELECT *
        FROM quiz_questions
        WHERE pdf_id=?
        AND id>?
        ORDER BY id
        LIMIT 1
    """, (question["pdf_id"], question_id))

    next_question = cursor.fetchone()

    # course name is already authorized in authorized_question_context
    # (joined from uploaded_pdfs with the current user's ownership check)
    course_name = question["pdf_course"]

    conn.close()

    is_correct = (
        selected_answer == question["correct_answer"]
    )

    end_time_str = session.get("quiz_end_time")
    if not end_time_str:
        flash("Quiz session expired. Please start the quiz again.", "warning")
        return redirect(url_for("ai_quiz.start_quiz", pdf_id=question["pdf_id"]))

    end_time = datetime.strptime(
        end_time_str,
        "%Y-%m-%d %H:%M:%S"
)

    remaining_seconds = max(
        int((end_time - datetime.now()).total_seconds()),
        0
)

    # Time is up: stop accepting answers and finalize the quiz.
    if remaining_seconds <= 0:
        return redirect(
            url_for("ai_quiz.result", pdf_id=question["pdf_id"])
        )

    # Prevent duplicate scoring for an already-answered question.
    answered = session.setdefault("quiz_answered", [])
    if question_id in answered:
        flash("This question was already answered.", "info")
        return redirect(
            url_for("ai_quiz.result", pdf_id=question["pdf_id"])
        )
    answered.append(question_id)
    session["quiz_answered"] = answered

    if is_correct:
        session["score"] = session.get("score", 0) + 1

    return render_template(
    "ai_quiz.html",
    question=question,
    question_no=question_no,
    total_questions=total_questions,
    pdf_id=question["pdf_id"],
    course_name=course_name,
    timer=remaining_seconds,
    show_feedback=True,
    is_correct=is_correct,
    selected_answer=selected_answer,
    next_question=next_question
)


# ==========================================
# Show Next Question
# ==========================================
@ai_quiz_bp.route("/question/<int:question_id>")
def show_question(question_id):

    user, question, error = authorized_question_context(question_id)
    if error:
        return _deny_quiz_access(error)

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT COUNT(*)
        FROM quiz_questions
        WHERE pdf_id=?
    """, (question["pdf_id"],))

    total_questions = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*)
        FROM quiz_questions
        WHERE pdf_id=?
        AND id<=?
    """, (question["pdf_id"], question_id))

    question_no = cursor.fetchone()[0]

    course_name = question["pdf_course"]

    conn.close()

    end_time_str = session.get("quiz_end_time")
    if not end_time_str:
        flash("Quiz session expired. Please start the quiz again.", "warning")
        return redirect(url_for("ai_quiz.start_quiz", pdf_id=question["pdf_id"]))

    end_time = datetime.strptime(
        end_time_str,
        "%Y-%m-%d %H:%M:%S"
)

    remaining_seconds = max(
        int((end_time - datetime.now()).total_seconds()),
        0
)

    if remaining_seconds <= 0:
        return redirect(
            url_for("ai_quiz.result", pdf_id=question["pdf_id"])
        )

    return render_template(
    "ai_quiz.html",
    question=question,
    question_no=question_no,
    total_questions=total_questions,
    pdf_id=question["pdf_id"],
    course_name=course_name,
    timer=remaining_seconds,
    show_feedback=False
)
#==========================================
# RESULT PAGE
#=========================================

@ai_quiz_bp.route("/result/<int:pdf_id>", methods=["GET", "POST"])
def result(pdf_id):

    user, pdf, error = authorized_quiz_context(pdf_id)
    if error:
        return _deny_quiz_access(error)

    score = session.get("score", 0)
    total_questions = session.get("total_questions", 0)

    percentage = 0

    if total_questions > 0:
        percentage = round((score / total_questions) * 100, 2)

    # Finalize the attempt exactly once: record the result, recent activity,
    # and a study-session row reflecting the real time spent on the quiz.
    if total_questions > 0 and not session.pop("quiz_completed", False):

        duration_minutes = 20
        start_str = session.get("quiz_start_time")
        if start_str:
            try:
                start = datetime.strptime(start_str, "%Y-%m-%d %H:%M:%S")
                duration_minutes = max(
                    1,
                    round((datetime.now() - start).total_seconds() / 60)
                )
            except ValueError:
                duration_minutes = 20

        save_quiz_result(
            user["id"],
            pdf_id,
            score,
            total_questions,
            percentage,
            pdf["course"],
            duration_minutes=duration_minutes
        )

        # Clear session values
        session.pop("score", None)
        session.pop("total_questions", None)
        session.pop("quiz_end_time", None)
        session.pop("quiz_answered", None)
        session.pop("quiz_start_time", None)

    return render_template(
        "result.html",
        score=score,
        total_questions=total_questions,
        percentage=percentage,
        pdf_id=pdf_id
    )