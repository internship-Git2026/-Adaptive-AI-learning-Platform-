import logging
import time
import uuid

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    abort,
)

from database import get_db
from course_access import has_course_access
from gate_course import GATE_SUBJECTS, NEET_SUBJECTS
from llm import GROQ_MODEL, _get_client, generate
from question_generator import _extract_json, _normalise_question, QuizGenerationError
from spaced_repetition import schedule_review

logger = logging.getLogger(__name__)

practice_bp = Blueprint("practice", __name__, url_prefix="/practice")

SUBJECTS_BY_COURSE = {
    "GATE": GATE_SUBJECTS,
    "NEET": NEET_SUBJECTS,
}

# Server-side cache for generated content. The Flask default session is a
# signed cookie with a ~4KB limit, so questions (which are large) are kept here
# keyed by a random token while only the token lives in the cookie.
_CACHE = {}
_CACHE_TTL_SECONDS = 6 * 60 * 60  # 6 hours
_MAX_CACHE_ENTRIES = 200

# -----------------------------------------------
# CACHE HELPERS
# -----------------------------------------------


def _cache_prune():
    now = time.time()
    stale = [k for k, v in _CACHE.items() if now - v["created_at"] > _CACHE_TTL_SECONDS]
    for key in stale:
        _CACHE.pop(key, None)
    if len(_CACHE) > _MAX_CACHE_ENTRIES:
        # Drop the oldest entries beyond the cap.
        for key in sorted(_CACHE, key=lambda k: _CACHE[k]["created_at"])[
            : len(_CACHE) - _MAX_CACHE_ENTRIES
        ]:
            _CACHE.pop(key, None)


def _cache_put(payload):
    _cache_prune()
    token = uuid.uuid4().hex
    payload["created_at"] = time.time()
    _CACHE[token] = payload
    return token


def _cache_get(token):
    if not token:
        return None
    entry = _CACHE.get(token)
    if not entry:
        return None
    if time.time() - entry["created_at"] > _CACHE_TTL_SECONDS:
        _CACHE.pop(token, None)
        return None
    return entry


# -----------------------------------------------
# ACCESS HELPERS
# -----------------------------------------------


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


def _require_login():
    user = _current_user()
    if not user:
        flash("Please sign in first.", "info")
        return None, redirect(url_for("signin.signin_page"))
    return user, None


def _require_course(user, course):
    if course not in SUBJECTS_BY_COURSE:
        abort(404)
    if user["payment_status"] != "PAID":
        flash("Please purchase a course plan to access AI features.", "warning")
        return redirect(url_for("plans.plans_page"))
    if not has_course_access(user["id"], course):
        flash(
            f"You are not enrolled in the {course} course. Please purchase the course to access.",
            "warning",
        )
        return redirect(url_for("my_courses.my_courses_page"))
    return None


def _find_subject(course, subject_key):
    for subject in SUBJECTS_BY_COURSE.get(course, []):
        if subject["key"] == subject_key:
            return subject
    return None


# -----------------------------------------------
# PER-SUBJECT PERFORMANCE (for adaptive quizzes)
# -----------------------------------------------


def get_weak_subjects(user_id, course, limit=3):
    """Return the weakest subjects for a user based on their quiz results.

    Primary method: uses per-question topic data from question_attempts
    (written by adaptive_answer) joined with quiz_questions.topic.
    Falls back to the old PDF-filename keyword method when no topic-tagged
    data exists yet for this user.

    Each entry: {key, name, description, icon, pct, attempted}.
    Subjects with no data are treated as weakest (pct=0).
    """
    subject_defs = SUBJECTS_BY_COURSE[course]
    subject_name_map = {s["name"].lower(): s["key"] for s in subject_defs}

    conn = get_db()
    cursor = conn.cursor()

    # ---------- Try topic-based approach first ----------
    cursor.execute(
        """
        SELECT qa.topic, qa.was_correct
        FROM question_attempts qa
        WHERE qa.user_id = ?
        """,
        (user_id,),
    )
    attempt_rows = cursor.fetchall()

    if attempt_rows:
        # Bucket by topic -> subject key
        buckets = {s["key"]: {"correct": 0, "total": 0} for s in subject_defs}
        for row in attempt_rows:
            topic = (row["topic"] or "General").lower()
            # Direct match: topic equals a subject name
            matched_key = subject_name_map.get(topic)
            if not matched_key:
                # Keyword fallback: check if any subject keyword is in the topic
                for subject in subject_defs:
                    for kw in subject["keywords"]:
                        if kw in topic:
                            matched_key = subject["key"]
                            break
                    if matched_key:
                        break
            if matched_key:
                buckets[matched_key]["total"] += 1
                if row["was_correct"]:
                    buckets[matched_key]["correct"] += 1

        items = []
        for subject in subject_defs:
            data = buckets[subject["key"]]
            pct = round((data["correct"] / data["total"]) * 100) if data["total"] > 0 else 0
            items.append(
                {
                    "key": subject["key"],
                    "name": subject["name"],
                    "description": subject["description"],
                    "icon": subject["icon"],
                    "pct": pct,
                    "attempted": data["total"] > 0,
                }
            )
        items.sort(key=lambda s: (s["attempted"], s["pct"]))
        conn.close()
        return items[:limit]

    # ---------- Fallback: old PDF-filename keyword method ----------
    cursor.execute(
        """
        SELECT qr.score, qr.total_questions, p.pdf_name, p.course
        FROM quiz_results qr
        JOIN uploaded_pdfs p ON qr.pdf_id = p.id
        WHERE qr.user_id = ?
        """,
        (user_id,),
    )
    results = cursor.fetchall()
    conn.close()

    buckets = {s["key"]: {"score": 0, "total": 0} for s in subject_defs}
    for row in results:
        combined = ((row["pdf_name"] or "") + " " + (row["course"] or "")).lower()
        for subject in subject_defs:
            for kw in subject["keywords"]:
                if kw in combined:
                    buckets[subject["key"]]["score"] += row["score"] or 0
                    buckets[subject["key"]]["total"] += row["total_questions"] or 0
                    break

    items = []
    for subject in subject_defs:
        data = buckets[subject["key"]]
        pct = round((data["score"] / data["total"]) * 100) if data["total"] > 0 else 0
        items.append(
            {
                "key": subject["key"],
                "name": subject["name"],
                "description": subject["description"],
                "icon": subject["icon"],
                "pct": pct,
                "attempted": data["total"] > 0,
            }
        )

    items.sort(key=lambda s: (s["attempted"], s["pct"]))
    return items[:limit]


# -----------------------------------------------
# AI GENERATION HELPERS
# -----------------------------------------------


def _extract_and_validate(output, expected_count):
    """Parse a Groq response into validated question dicts."""
    data = _extract_json(output)
    if not isinstance(data, list):
        raise QuizGenerationError("json_structure", "AI response was not a questions array.")

    validated = []
    for item in data:
        try:
            validated.append(_normalise_question(item))
        except QuizGenerationError:
            continue
        if len(validated) >= expected_count:
            break

    if not validated:
        raise QuizGenerationError("validation", "AI returned questions that failed validation.")
    return validated


def generate_subject_summary(course, subject):
    """Return an AI summary dict for a subject: {overview, key_concepts, weightage, focus_areas, tips}."""
    prompt = f"""
You are an expert {course} trainer.

Write a concise study summary for the {course} subject "{subject['name']}".
Covered syllabus focus: {subject['description']}

Return ONLY valid JSON with exactly this structure:
{{
  "overview": "2-3 sentence overview of the subject and why it matters for {course}",
  "key_concepts": ["concept 1", "concept 2", "concept 3", "concept 4", "concept 5"],
  "weightage": "Typical exam weightage statement (e.g. '12-15% of the paper')",
  "focus_areas": ["1-2 sentence high-yield focus area 1", "focus area 2"],
  "tips": "1-2 sentence preparation tip"
}}

Rules:
1. Keep key_concepts to exactly 5 short items.
2. Keep overview under 50 words.
3. Do NOT write markdown. Do NOT write ```json.
"""
    try:
        output = generate(prompt, temperature=0.4)
        data = _extract_json(output)
        if not isinstance(data, dict):
            raise QuizGenerationError("json_structure", "AI returned a non-object summary.")
        data["overview"] = str(data.get("overview", "")).strip()
        concepts = data.get("key_concepts")
        if not isinstance(concepts, list) or not concepts:
            concepts = [subject["description"]]
        data["key_concepts"] = [str(c).strip() for c in concepts][:8]
        data["weightage"] = str(data.get("weightage", "")).strip()
        data["focus_areas"] = data.get("focus_areas", [])
        data["tips"] = str(data.get("tips", "")).strip()
        return data
    except QuizGenerationError as exc:
        logger.error("PRACTICE: subject summary failed (%s): %s", exc.stage, exc.message)
        return {
            "overview": f"{subject['name']} is a core {course} subject covering {subject['description']}.",
            "key_concepts": [subject["description"]],
            "weightage": "Check your uploaded material and exam syllabus for exact weightage.",
            "focus_areas": ["Focus on previous-year questions for this subject."],
            "tips": "Practice regularly and review your mistakes.",
        }


def generate_subject_questions(course, subject, count=5):
    """Generate subject-wise practice questions (reuses the validated quiz pipeline)."""
    brief = (
        f"Subject: {subject['name']}\n"
        f"Exam: {course}\n"
        f"Syllabus focus: {subject['description']}\n\n"
        f"Generate multiple-choice questions that reflect the standard {course} "
        f"syllabus for {subject['name']}."
    )
    from question_generator import generate_questions

    return generate_questions(brief, question_count=count, difficulty="Medium")


_DIFFICULTY_TIERS = ["Easy", "Medium", "Hard"]


def generate_adaptive_questions(user_id, course, count=8):
    """Generate a quiz targeting the learner's weakest subject areas.

    Generates exactly `count` questions distributed across weak subjects
    and difficulty tiers. Each question carries 'topic' and 'difficulty'
    fields for the adaptive engine.
    """
    count = max(4, min(count, 15))
    weak = get_weak_subjects(user_id, course, limit=3)
    if not weak:
        weak = [{"name": "General", "pct": 0, "attempted": False, "description": "General topics"}]

    # Build spec lines — only as many as the requested count
    spec_lines_parts = []
    idx = 0
    for s in weak:
        for diff in _DIFFICULTY_TIERS:
            if idx >= count:
                break
            spec_lines_parts.append(f"{s['name']} / {diff}")
            idx += 1
        if idx >= count:
            break

    # If we have fewer specs than count (e.g. 1 weak subject), fill remaining
    while len(spec_lines_parts) < count:
        last = spec_lines_parts[-1] if spec_lines_parts else f"{weak[0]['name']} / Medium"
        spec_lines_parts.append(last)

    spec_lines = "\n".join(spec_lines_parts)

    if weak[0].get("attempted"):
        weak_text = "\n".join(
            f"- {s['name']} (accuracy {s['pct']}%): {s['description']}"
            for s in weak
        )
    else:
        weak_text = ", ".join(s["name"] for s in weak)

    prompt = f"""Generate exactly {count} MCQ for {course} exam.

Weak areas:
{weak_text}

Generate one question for each line below (exactly {count} questions):
{spec_lines}

Return a JSON array with exactly {count} objects. Each object: question, options (4 strings), correct_answer (0-3), explanation, topic, difficulty (Easy/Medium/Hard).
Return ONLY the JSON array. No markdown, no extra text."""

    last_error = None
    for attempt in range(2):
        try:
            output = generate(prompt, temperature=0.5)
        except Exception as exc:
            logger.error("ADAPTIVE: Groq request failed: %s", exc)
            raise QuizGenerationError("groq_request", "AI service request failed.")

        if not output:
            raise QuizGenerationError("groq_response", "AI service returned an empty response.")

        try:
            return _extract_and_validate(output, count)
        except QuizGenerationError as exc:
            last_error = exc
            logger.warning("ADAPTIVE: parse attempt %d failed: %s", attempt + 1, exc.message)
            continue

    raise last_error


def next_adaptive_question(entry, last_index, was_correct):
    """Select the next pool index for the adaptive quiz.

    On correct answer: same topic, one difficulty tier HARDER.
    On incorrect answer: same topic, one difficulty tier EASIER.
    Falls back to next unanswered in original pool order.
    """
    questions = entry["questions"]
    answered = entry.get("answers", {})
    order = entry.get("order", [])

    # Convert position-based answered dict to pool-index-based set
    answered_pool_indices = set()
    for pos in answered:
        if 1 <= pos <= len(order):
            answered_pool_indices.add(order[pos - 1])

    # Last question the student saw (pool index)
    last_pool_idx = order[last_index - 1]
    last_q = questions[last_pool_idx]
    last_topic = last_q.get("topic", "General")
    last_diff = last_q.get("difficulty", "Medium")

    # Determine target difficulty
    diff_idx = _DIFFICULTY_TIERS.index(last_diff) if last_diff in _DIFFICULTY_TIERS else 1
    if was_correct:
        target_diff = _DIFFICULTY_TIERS[min(diff_idx + 1, len(_DIFFICULTY_TIERS) - 1)]
    else:
        target_diff = _DIFFICULTY_TIERS[max(diff_idx - 1, 0)]

    # Find unanswered question with same topic + target difficulty
    for i, q in enumerate(questions):
        if i in answered_pool_indices:
            continue
        if q.get("topic") == last_topic and q.get("difficulty") == target_diff:
            return i

    # Fallback: next unanswered in original pool order
    for i in range(len(questions)):
        if i not in answered_pool_indices:
            return i

    # All questions answered
    return None


# ===============================================
# ASK AI (platform assistant, works for guests)
# ===============================================

_ASK_AI_SYSTEM = """
You are the friendly assistant for "Adaptive Learning" (branded AdaptiveGATE AI), a
GATE/NEET exam preparation platform.

Help new and existing users understand HOW THIS WEBSITE WORKS. You may only answer
questions about this platform: features, courses, pricing, how to sign up, how to
upload PDFs, how to generate AI quizzes, how to use adaptive quizzes, subject-wise
practice, progress tracking, and common troubleshooting.

Platform facts you can rely on:
- Courses: GATE (₹1,000 lifetime), NEET (₹1,000 lifetime), GATE+NEET combo (₹1,500 lifetime).
- Users sign up, choose a course, and after payment get lifetime access.
- They can upload PDFs of study material; the AI generates multiple-choice quizzes from the PDF.
- "Start Adaptive Quiz" builds a quiz from the user's weaker subjects based on past quiz performance.
- "Practice Subject" offers subject-wise questions with an AI summary of the subject.
- The dashboard, My Courses, Progress and AI Doubt Solver help track and improve learning.

Rules:
- Answer only about this platform. If asked about anything unrelated (general knowledge,
  coding, other websites, personal advice), politely say you can only help with this
  website and suggest how to use it.
- Be concise and friendly. Use short paragraphs or bullet points.
"""

_ASK_AI_HISTORY_KEY = "ask_ai_history"


def generate_ask_ai_reply(question, history):
    """Build the platform-only assistant reply for `question`."""
    messages = [{"role": "system", "content": _ASK_AI_SYSTEM}]
    for turn in history[-6:]:
        messages.append({"role": "user", "content": turn["q"]})
        messages.append({"role": "assistant", "content": turn["a"]})
    messages.append({"role": "user", "content": question})

    response = _get_client().chat.completions.create(
        model=GROQ_MODEL,
        messages=messages,
        temperature=0.6,
    )
    content = response.choices[0].message.content
    return (content or "").strip()


@practice_bp.route("/ask-ai", methods=["GET", "POST"])
def ask_ai():
    user = _current_user()
    history = session.get(_ASK_AI_HISTORY_KEY, [])

    if request.method == "POST":
        question = (request.form.get("question") or "").strip()
        if not question:
            flash("Please type a question first.", "info")
        else:
            try:
                reply = generate_ask_ai_reply(question, history)
            except Exception as exc:
                logger.error("ASK_AI: request failed: %s", exc)
                flash("The AI assistant could not be reached. Please try again.", "error")
                reply = None
            if reply:
                history = history + [{"q": question, "a": reply}]
                session[_ASK_AI_HISTORY_KEY] = history[-8:]

    suggestions = [
        "How do I get started?",
        "What courses are available and how much do they cost?",
        "How do I upload a PDF and generate a quiz?",
        "How does the adaptive quiz work?",
        "What is the Practice Subject feature?",
        "How do I track my progress?",
    ]

    return render_template(
        "ask_ai.html",
        active_page="ask_ai",
        user=user,
        history=history,
        suggestions=suggestions,
    )


# ===============================================
# SUBJECT PRACTICE
# ===============================================


def _practice_token_key(course, subject_key):
    return f"practice_{course}_{subject_key}_token"


@practice_bp.route("/subject/<course>/<subject_key>")
def subject_practice(course, subject_key):
    user, error_redirect = _require_login()
    if error_redirect:
        return error_redirect

    denied = _require_course(user, course)
    if denied:
        return denied

    subject = _find_subject(course, subject_key)
    if not subject:
        abort(404)

    token = session.get(_practice_token_key(course, subject_key))
    entry = _cache_get(token) if token else None

    if not entry or entry.get("user_id") != user["id"]:
        summary = generate_subject_summary(course, subject)
        try:
            questions = generate_subject_questions(course, subject, count=5)
        except QuizGenerationError as exc:
            logger.error("PRACTICE: question generation failed (%s): %s", exc.stage, exc.message)
            questions = []
        entry = {
            "user_id": user["id"],
            "course": course,
            "subject_key": subject_key,
            "summary": summary,
            "questions": questions,
        }
        token = _cache_put(entry)
        session[_practice_token_key(course, subject_key)] = token

    return render_template(
        "practice_subject.html",
        active_page="courses",
        user=user,
        course=course,
        subject=subject,
        summary=entry["summary"],
        questions=entry["questions"],
        question_count=len(entry["questions"]),
    )


@practice_bp.route("/subject/<course>/<subject_key>/refresh", methods=["POST"])
def subject_practice_refresh(course, subject_key):
    user, error_redirect = _require_login()
    if error_redirect:
        return error_redirect

    denied = _require_course(user, course)
    if denied:
        return denied

    subject = _find_subject(course, subject_key)
    if not subject:
        abort(404)

    try:
        questions = generate_subject_questions(course, subject, count=5)
    except QuizGenerationError as exc:
        logger.error("PRACTICE: refresh failed (%s): %s", exc.stage, exc.message)
        flash("Could not generate new questions. Please try again.", "error")
        return redirect(
            url_for("practice.subject_practice", course=course, subject_key=subject_key)
        )

    summary = generate_subject_summary(course, subject)
    entry = {
        "user_id": user["id"],
        "course": course,
        "subject_key": subject_key,
        "summary": summary,
        "questions": questions,
    }
    token = _cache_put(entry)
    session[_practice_token_key(course, subject_key)] = token

    return redirect(
        url_for("practice.subject_practice", course=course, subject_key=subject_key)
    )


# ===============================================
# ADAPTIVE QUIZ
# ===============================================

_ADAPTIVE_SESSION_TOKEN = "adaptive_session_token"


def _adaptive_cache_questions(token):
    entry = _cache_get(token)
    if not entry or entry.get("kind") != "adaptive":
        return None
    return entry


@practice_bp.route("/adaptive/<course>")
def adaptive_quiz(course):
    user, error_redirect = _require_login()
    if error_redirect:
        return error_redirect

    denied = _require_course(user, course)
    if denied:
        return denied

    weak = get_weak_subjects(user["id"], course, limit=3)

    in_progress = False
    token = session.get(_ADAPTIVE_SESSION_TOKEN)
    entry = _adaptive_cache_questions(token) if token else None
    if entry and entry.get("user_id") == user["id"] and entry.get("course") == course:
        in_progress = True

    return render_template(
        "adaptive_quiz.html",
        active_page="courses",
        user=user,
        course=course,
        weak=weak,
        in_progress=in_progress,
        start_index=1,
    )


@practice_bp.route("/adaptive/<course>/generate", methods=["POST"])
def adaptive_quiz_generate(course):
    user, error_redirect = _require_login()
    if error_redirect:
        return error_redirect

    denied = _require_course(user, course)
    if denied:
        return denied

    try:
        count = int(request.form.get("question_count", 8))
    except (TypeError, ValueError):
        count = 8
    count = max(4, min(count, 15))

    try:
        questions = generate_adaptive_questions(user["id"], course, count=count)
    except QuizGenerationError as exc:
        logger.error("ADAPTIVE: generation failed (%s): %s", exc.stage, exc.message)
        flash("Could not generate the adaptive quiz. Please try again.", "error")
        return redirect(url_for("practice.adaptive_quiz", course=course))

    entry = {
        "kind": "adaptive",
        "user_id": user["id"],
        "course": course,
        "questions": questions,
        "answers": {},
        "score": 0,
        "order": [],
        "target_count": count,
        "started_at": time.time(),
    }
    token = _cache_put(entry)
    session[_ADAPTIVE_SESSION_TOKEN] = token

    return redirect(url_for("practice.adaptive_question", course=course, index=1))


def _adaptive_entry_or_redirect(course, user):
    """Return (entry, None) or (None, redirect_response)."""
    token = session.get(_ADAPTIVE_SESSION_TOKEN)
    entry = _adaptive_cache_questions(token)
    if not entry or entry.get("user_id") != user["id"] or entry.get("course") != course:
        flash("No adaptive quiz in progress. Please generate one first.", "info")
        return None, redirect(url_for("practice.adaptive_quiz", course=course))
    return entry, None


@practice_bp.route("/adaptive/<course>/question/<int:index>")
def adaptive_question(course, index):
    user, error_redirect = _require_login()
    if error_redirect:
        return error_redirect

    denied = _require_course(user, course)
    if denied:
        return denied

    entry, redirect_response = _adaptive_entry_or_redirect(course, user)
    if redirect_response:
        return redirect_response

    questions = entry["questions"]
    order = entry.setdefault("order", [])
    total_pool = len(questions)
    target_count = entry.get("target_count", total_pool)
    answered_count = len(entry.get("answers", {}))

    # index = the Nth question the student sees (1-based)
    if index < 1:
        return redirect(url_for("practice.adaptive_question", course=course, index=1))

    # First question: pick from pool if order is empty
    if not order:
        order.append(0)  # start with the first question in the pool
        _CACHE[session.get(_ADAPTIVE_SESSION_TOKEN, "")] = entry

    # If we've already served this many questions and this is beyond, go to result
    if index > len(order):
        return redirect(url_for("practice.adaptive_result", course=course))

    # Ensure the pool index for this position is in the order
    pool_idx = order[index - 1]
    question = questions[pool_idx]
    answered = entry.get("answers", {}).get(index)

    # Determine next_index for the "Next Question" button
    next_index = None
    if not answered:
        # Stop once we've shown the target number of questions
        if index < target_count:
            next_index = index + 1
    else:
        # Already answered (revisiting); next_index was set at answer time
        next_index = entry.get("next_index")

    return render_template(
        "adaptive_quiz.html",
        active_page="courses",
        user=user,
        course=course,
        question=question,
        index=index,
        total=target_count,
        answered=answered,
        session_score=entry.get("score", 0),
        next_index=next_index,
        start_index=1,
    )


@practice_bp.route("/adaptive/<course>/answer/<int:index>", methods=["POST"])
def adaptive_answer(course, index):
    user, error_redirect = _require_login()
    if error_redirect:
        return error_redirect

    denied = _require_course(user, course)
    if denied:
        return denied

    entry, redirect_response = _adaptive_entry_or_redirect(course, user)
    if redirect_response:
        return redirect_response

    token = session.get(_ADAPTIVE_SESSION_TOKEN)
    questions = entry["questions"]
    order = entry.setdefault("order", [])
    total_pool = len(questions)
    answered_set = set(entry.get("answers", {}).keys())

    # index = Nth question the student sees (1-based)
    if index < 1 or index > len(order):
        return redirect(url_for("practice.adaptive_result", course=course))

    try:
        selected = int(request.form.get("answer"))
    except (KeyError, TypeError, ValueError):
        flash("Invalid answer submitted.", "error")
        return redirect(url_for("practice.adaptive_question", course=course, index=index))

    answers = entry.setdefault("answers", {})
    if index not in answers:
        answers[index] = selected
        pool_idx = order[index - 1]
        was_correct = selected == questions[pool_idx]["correct_answer"]
        if was_correct:
            entry["score"] = entry.get("score", 0) + 1

        # Record spaced-repetition data for this topic
        try:
            schedule_review(
                user_id=user["id"],
                subject=course,
                topic=questions[pool_idx].get("topic", "General"),
                was_correct=was_correct,
            )
        except Exception as exc:
            logger.warning("ADAPTIVE: schedule_review failed: %s", exc)

        # Log the individual question attempt for per-topic analytics
        try:
            conn = get_db()
            conn.execute(
                "INSERT INTO question_attempts (user_id, topic, was_correct) VALUES (?, ?, ?)",
                (user["id"], questions[pool_idx].get("topic", "General"), 1 if was_correct else 0),
            )
            conn.commit()
            conn.close()
        except Exception as exc:
            logger.warning("ADAPTIVE: question_attempts insert failed: %s", exc)

        # Compute the next pool index using adaptive logic
        next_pool_idx = next_adaptive_question(entry, index, was_correct)
        target_count = entry.get("target_count", len(questions))

        if next_pool_idx is not None and next_pool_idx not in answered_set and index < target_count:
            # Add the next question to the order
            order.append(next_pool_idx)
            next_index = index + 1
        else:
            # Reached target count or no more questions available
            next_index = None

        entry["next_index"] = next_index
        _CACHE[token] = entry
    else:
        # Already answered — reuse stored next_index
        next_index = entry.get("next_index")

    target_count = entry.get("target_count", len(questions))
    pool_idx = order[index - 1]
    return render_template(
        "adaptive_quiz.html",
        active_page="courses",
        user=user,
        course=course,
        question=questions[pool_idx],
        index=index,
        total=target_count,
        answered=selected,
        is_correct=selected == questions[pool_idx]["correct_answer"],
        next_index=next_index,
        session_score=entry.get("score", 0),
        start_index=1,
    )


@practice_bp.route("/adaptive/<course>/result")
def adaptive_result(course):
    user, error_redirect = _require_login()
    if error_redirect:
        return error_redirect

    denied = _require_course(user, course)
    if denied:
        return denied

    entry, redirect_response = _adaptive_entry_or_redirect(course, user)
    if redirect_response:
        return redirect_response

    questions = entry["questions"]
    order = entry.get("order", [])
    answers = entry.get("answers", {})
    score = entry.get("score", 0)
    answered_count = len(answers)
    total = entry.get("target_count", len(order))
    percentage = round((score / total) * 100) if total else 0

    # Build an ordered list of questions that were actually shown, in the
    # order the student saw them.  The template iterates this with
    # loop.index matching the keys in `answers`.
    ordered_questions = [questions[idx] for idx in order]

    return render_template(
        "adaptive_result.html",
        active_page="courses",
        user=user,
        course=course,
        score=score,
        total=total,
        answered_count=answered_count,
        percentage=percentage,
        questions=ordered_questions,
        answers=answers,
    )


@practice_bp.route("/adaptive/<course>/restart", methods=["POST"])
def adaptive_restart(course):
    session.pop(_ADAPTIVE_SESSION_TOKEN, None)
    return redirect(url_for("practice.adaptive_quiz", course=course))
