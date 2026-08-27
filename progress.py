from flask import Blueprint, render_template, session, redirect, url_for, flash, jsonify
from database import get_db
from spaced_repetition import get_due_revisions
from practice import get_weak_subjects
from study_resources import get_resources_for_topic

progress_bp = Blueprint('progress', __name__, url_prefix='/progress')

@progress_bp.route('/')
def progress_page():
    user_email = session.get("user_email")
    if not user_email:
        flash("Please sign in first.", "info")
        return redirect(url_for('signin.signin_page'))

    conn = get_db()
    cursor = conn.cursor()

    # Get user details
    cursor.execute("SELECT * FROM users WHERE email = ?", (user_email,))
    user = cursor.fetchone()
    if not user:
        conn.close()
        session.clear()
        return redirect(url_for('signin.signin_page'))

    user_id = user['id']

    # 1. Study Time (from study_sessions)
    cursor.execute("SELECT SUM(duration_minutes) as total_min FROM study_sessions WHERE user_id = ?", (user_id,))
    study_row = cursor.fetchone()
    total_minutes = study_row['total_min'] if study_row and study_row['total_min'] else 0
    study_hours = round(total_minutes / 60.0, 1)

    # Weekly Study Hours (Last 7 Days)

    cursor.execute("""
    SELECT strftime('%w', session_start) as day_num,
           SUM(duration_minutes) as duration
    FROM study_sessions
    WHERE user_id=?
    AND session_start >= datetime('now','-7 days')
    GROUP BY day_num
""", (user_id,))

    sessions = cursor.fetchall()

    day_mapping = {
        0: "Sun",
        1: "Mon",
        2: "Tue",
        3: "Wed",
        4: "Thu",
        5: "Fri",
        6: "Sat"
    }

    study_dict = {
        day: 0.0
        for day in day_mapping.values()
    }

    for s in sessions:
        day_name = day_mapping[int(s["day_num"])]
        study_dict[day_name] = round(
           s["duration"] / 60.0,
           1
    )

    weekly_study_data = [
        {
            "day": day,
            "hours": study_dict[day]
        }
        for day in [
            "Mon",
            "Tue",
            "Wed",
            "Thu",
            "Fri",
            "Sat",
            "Sun"
        ]
    ]
        
    # 2. Questions Solved & Accuracy
    cursor.execute("""
        SELECT COUNT(*) as quiz_count, SUM(total_questions) as total_q, SUM(score) as correct_q, AVG(percentage) as avg_pct
        FROM quiz_results
        WHERE user_id = ?
    """, (user_id,))
    quiz_summary = cursor.fetchone()

    total_quizzes = quiz_summary['quiz_count'] if quiz_summary and quiz_summary['quiz_count'] else 0

    questions_solved = quiz_summary['total_q'] if quiz_summary and quiz_summary['total_q'] else 0

    correct_answers = quiz_summary['correct_q'] if quiz_summary and quiz_summary['correct_q'] else 0

    accuracy = round(quiz_summary['avg_pct']) if quiz_summary and quiz_summary['avg_pct'] else 0
    
    # Total PDFs Uploaded
    cursor.execute("""
        SELECT COUNT(*) AS total_pdfs
        FROM uploaded_pdfs
        WHERE user_id=?
    """, (user_id,))

    pdf_row = cursor.fetchone()

    total_pdfs = pdf_row["total_pdfs"] if pdf_row else 0
    
    # Highest and Lowest Quiz Score
    cursor.execute("""
        SELECT
           MAX(percentage) AS highest_score,
           MIN(percentage) AS lowest_score
        FROM quiz_results
        WHERE user_id=?
    """, (user_id,))

    score_row = cursor.fetchone()

    highest_score = round(score_row["highest_score"]) if score_row["highest_score"] else 0
    lowest_score = round(score_row["lowest_score"]) if score_row["lowest_score"] else 0

    # 3. Accuracy Trend (Last 5 Quizzes)
    cursor.execute("""
        SELECT q.percentage, q.completed_at, p.pdf_name
        FROM quiz_results q
        JOIN uploaded_pdfs p ON q.pdf_id = p.id
        WHERE q.user_id = ?
        ORDER BY q.completed_at ASC
        LIMIT 5
    """, (user_id,))
    trend_rows = cursor.fetchall()
    
    accuracy_trend = []
    if not trend_rows:
        accuracy_trend = []
    else:
        for idx, row in enumerate(trend_rows):
            accuracy_trend.append({
                "label": f"Quiz {idx+1}",
                "percentage": round(row['percentage'])
            })

    # 4. Questions Solved trend (last 5 quizzes)
    questions_solved_trend = []
    if not trend_rows:
        questions_solved_trend = []
    else:
        cursor.execute("""
            SELECT score, total_questions
            FROM quiz_results
            WHERE user_id = ?
            ORDER BY completed_at ASC
            LIMIT 5
        """, (user_id,))
        for idx, row in enumerate(cursor.fetchall()):
            questions_solved_trend.append({
                "label": f"Quiz {idx+1}",
                "correct": row['score'],
                "total": row['total_questions']
            })

    # 5. Quiz History Table
    cursor.execute("""
        SELECT q.id, q.score, q.total_questions, q.percentage, q.completed_at, p.pdf_name, p.course
        FROM quiz_results q
        JOIN uploaded_pdfs p ON q.pdf_id = p.id
        WHERE q.user_id = ?
        ORDER BY q.completed_at DESC
    """, (user_id,))
    history_rows = cursor.fetchall()
    quiz_history = []
    
    for row in history_rows:
        quiz_history.append({
            "id": row['id'],
            "pdf_name": row['pdf_name'],
            "course": row['course'],
            "score": row['score'],
            "total_questions": row['total_questions'],
            "percentage": round(row['percentage']),
            "completed_at": row['completed_at']
        })

    # 6. Due Revisions (spaced repetition)
    due_revisions = get_due_revisions(user_id)
    # Add days_overdue to each revision for display
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    for rev in due_revisions:
        try:
            next_rev = datetime.strptime(rev["next_revision"], "%Y-%m-%d")
            today_dt = datetime.strptime(today, "%Y-%m-%d")
            rev["days_overdue"] = max(0, (today_dt - next_rev).days)
        except (ValueError, KeyError):
            rev["days_overdue"] = 0

    # 7. Weak Subjects (loaded async — no API calls here)
    user_course = user["selected_course"] or "GATE"
    if user_course not in ("GATE", "NEET"):
        user_course = "GATE"
    weak_subjects = get_weak_subjects(user_id, user_course, limit=5)
    # Attach empty resources list — filled by the async endpoint
    for subj in weak_subjects:
        subj["resources"] = []

    conn.close()

    return render_template(
        'progress.html',
        active_page='progress',
        user=user,
        study_hours=study_hours,
        questions_solved=questions_solved,
        correct_answers=correct_answers,
        accuracy=accuracy,
        total_pdfs=total_pdfs,
        total_quizzes=total_quizzes,
        highest_score=highest_score,
        lowest_score=lowest_score,
        weekly_study_data=weekly_study_data,
        accuracy_trend=accuracy_trend,
        questions_solved_trend=questions_solved_trend,
        quiz_history=quiz_history,
        due_revisions=due_revisions,
        weak_subjects=weak_subjects,
        user_course=user_course
    )


@progress_bp.route('/weak-subjects')
def weak_subjects_api():
    """Return weak subjects with YouTube resources as JSON.

    Called asynchronously by the progress page after it loads,
    so the main page renders instantly without waiting for
    Groq + YouTube API calls.
    """
    user_email = session.get("user_email")
    if not user_email:
        return jsonify({"error": "not logged in"}), 401

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE email = ?", (user_email,))
    user = cursor.fetchone()
    conn.close()

    if not user:
        return jsonify({"error": "user not found"}), 404

    user_id = user["id"]
    user_course = user["selected_course"] or "GATE"
    if user_course not in ("GATE", "NEET"):
        user_course = "GATE"

    weak_subjects = get_weak_subjects(user_id, user_course, limit=5)

    # Fetch YouTube resources for each weak subject (this is the slow part)
    for subj in weak_subjects:
        try:
            subj["resources"] = get_resources_for_topic(user_course, subj["key"])
        except Exception:
            subj["resources"] = []

    return jsonify({
        "weak_subjects": weak_subjects,
        "course": user_course,
    })
