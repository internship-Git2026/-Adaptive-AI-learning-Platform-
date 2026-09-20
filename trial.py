import os
import random
import string
import datetime
from flask import Blueprint, render_template, request, redirect, url_for, session, make_response, jsonify, flash
from database import get_db
from quiz_service import save_ai_quiz

trial_bp = Blueprint('trial', __name__, url_prefix='/trial')

def generate_random_string(length=8):
    letters_and_digits = string.ascii_uppercase + string.digits
    return ''.join(random.choice(letters_and_digits) for i in range(length))

def get_current_trial():
    trial_id = request.cookies.get("trial_id") or session.get("trial_id")
    if not trial_id:
        return None
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM guest_trials WHERE trial_id = ?", (trial_id,))
    trial = cursor.fetchone()
    conn.close()
    return trial

@trial_bp.route('/gate', methods=['GET'])
def start_gate():
    return start_trial('GATE')

@trial_bp.route('/neet', methods=['GET'])
def start_neet():
    return start_trial('NEET')

def start_trial(course):
    fingerprint = (request.args.get("fp") or "").strip()
    ip = request.remote_addr or "unknown"

    trial_id_cookie = request.cookies.get("trial_id")
    if trial_id_cookie:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM guest_trials WHERE trial_id = ?", (trial_id_cookie,))
        trial = cursor.fetchone()
        conn.close()
        if trial:
            if trial['course'] == course:
                # Same course: show used page or resume in-progress trial
                if trial['trial_used'] or (trial['pdf_uploaded'] and trial['quiz_generated']):
                    return redirect(url_for('trial.trial_used_page'))
                return redirect(url_for('trial.dashboard'))
            # Different course: fall through to create a new trial

    conn = get_db()
    cursor = conn.cursor()

    # ---- Trial abuse prevention ----
    # Device fingerprint (when the client sends one): a used/completed trial
    # on this device blocks new trials even after cookies are cleared.
    if fingerprint:
        cursor.execute(
            "SELECT * FROM guest_trials WHERE fingerprint = ? ORDER BY id DESC LIMIT 1",
            (fingerprint,)
        )
        prior = cursor.fetchone()
        if prior:
            if prior['course'] == course:
                # Same course: block used or resume in-progress
                used = prior['trial_used'] or (prior['pdf_uploaded'] and prior['quiz_generated'])
                if used:
                    conn.close()
                    flash("Your free trial has already been used on this device.", "warning")
                    return redirect(url_for('trial.trial_used_page'))
                conn.close()
                session["trial_id"] = prior['trial_id']
                response = make_response(redirect(url_for('trial.dashboard')))
                response.set_cookie("trial_id", prior['trial_id'], max_age=30*24*60*60, httponly=True)
                response.set_cookie("browser_token", prior['browser_token'], max_age=30*24*60*60, httponly=True)
                return response
            # Different course: fall through to create a new trial
    else:
        # No device fingerprint (JS disabled/blocked): fall back to a per-IP cap
        cursor.execute("""
            SELECT COUNT(*) AS cnt FROM guest_trials
            WHERE ip = ? AND (trial_used = 1 OR (pdf_uploaded = 1 AND quiz_generated = 1))
        """, (ip,))
        if cursor.fetchone()["cnt"] >= 3:
            conn.close()
            flash("Too many free trials from this network. Please sign up for full access.", "warning")
            return redirect(url_for('trial.trial_used_page'))

    trial_id = f"TRIAL_{generate_random_string(8)}"
    browser_token = f"TOKEN_{generate_random_string(16)}"
    
    # Check if this browser token already exists to prevent duplicate abuse
    try:
        cursor.execute("""
            INSERT INTO guest_trials (trial_id, browser_token, course, pdf_credit, quiz_credit, trial_used, fingerprint, ip)
            VALUES (?, ?, ?, 1, 1, 0, ?, ?)
        """, (trial_id, browser_token, course, fingerprint or None, ip))
        conn.commit()
    except Exception as e:
        # Fallback if token conflict
        trial_id = f"TRIAL_{generate_random_string(8)}"
        browser_token = f"TOKEN_{generate_random_string(16)}"
        cursor.execute("""
            INSERT INTO guest_trials (trial_id, browser_token, course, pdf_credit, quiz_credit, trial_used, fingerprint, ip)
            VALUES (?, ?, ?, 1, 1, 0, ?, ?)
        """, (trial_id, browser_token, course, fingerprint or None, ip))
        conn.commit()
        
    conn.close()

    session["trial_id"] = trial_id
    
    response = make_response(redirect(url_for('trial.dashboard')))
    # Set secure cookie valid for 30 days
    response.set_cookie("trial_id", trial_id, max_age=30*24*60*60, httponly=True)
    response.set_cookie("browser_token", browser_token, max_age=30*24*60*60, httponly=True)
    return response

@trial_bp.route('/restore', methods=['GET'])
def restore_cookie():
    trial_id = request.args.get("trial_id")
    browser_token = request.args.get("browser_token")
    if not trial_id or not browser_token:
        return jsonify({"success": False, "error": "Missing parameters"}), 400

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM guest_trials WHERE trial_id = ? AND browser_token = ?", (trial_id, browser_token))
    trial = cursor.fetchone()
    conn.close()

    if trial:
        session["trial_id"] = trial_id
        response = make_response(jsonify({"success": True}))
        response.set_cookie("trial_id", trial_id, max_age=30*24*60*60, httponly=True)
        response.set_cookie("browser_token", browser_token, max_age=30*24*60*60, httponly=True)
        return response
    
    return jsonify({"success": False, "error": "Trial session not found"}), 404

@trial_bp.route('/', methods=['GET'])
def dashboard():
    trial = get_current_trial()
    if not trial:
        flash("Start a trial first.", "info")
        return redirect(url_for('main.home'))

    if trial['trial_used'] or (trial['pdf_uploaded'] and trial['quiz_generated']):
        # If they already finished the quiz, let them see their results if pdf exists
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM uploaded_pdfs WHERE trial_id = ?", (trial['trial_id'],))
        pdf = cursor.fetchone()
        conn.close()
        if pdf:
            return redirect(url_for('trial.result_page', pdf_id=pdf['id']))
        return redirect(url_for('trial.trial_used_page'))

    # Fetch uploaded PDF if any
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM uploaded_pdfs WHERE trial_id = ?", (trial['trial_id'],))
    pdf = cursor.fetchone()
    
    has_quiz = False
    pdf_id = None
    if pdf:
        pdf_id = pdf['id']
        cursor.execute("SELECT COUNT(*) FROM quiz_questions WHERE pdf_id = ?", (pdf['id'],))
        has_quiz = cursor.fetchone()[0] > 0
        
    conn.close()

    return render_template(
        "trial.html",
        trial=trial,
        pdf=pdf,
        pdf_id=pdf_id,
        has_quiz=has_quiz
    )

@trial_bp.route('/generate_quiz/<int:pdf_id>', methods=['POST'])
def generate_quiz(pdf_id):
    trial = get_current_trial()
    if not trial:
        flash("Session expired.", "error")
        return redirect(url_for('main.home'))

    if trial['quiz_credit'] <= 0:
        flash("You have already used your free quiz generation.", "warning")
        return redirect(url_for('trial.dashboard'))

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM uploaded_pdfs WHERE id = ? AND trial_id = ?", (pdf_id, trial['trial_id']))
    pdf = cursor.fetchone()
    conn.close()

    if not pdf:
        flash("PDF not found.", "error")
        return redirect(url_for('trial.dashboard'))

    # Generate quiz using existing quiz_service
    session["question_count"] = 10
    session["difficulty"] = "Medium"
    success, message = save_ai_quiz(pdf_id, pdf['extracted_text'])

    if success:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE guest_trials
            SET quiz_credit = 0, quiz_generated = 1
            WHERE trial_id = ?
        """, (trial['trial_id'],))
        conn.commit()
        conn.close()
        return redirect(url_for('trial.start_quiz', pdf_id=pdf_id))
    else:
        flash("Quiz generation failed. Please try again.", "error")
        return redirect(url_for('trial.dashboard'))

@trial_bp.route('/quiz/start/<int:pdf_id>')
def start_quiz(pdf_id):
    trial = get_current_trial()
    if not trial:
        flash("Session expired.", "error")
        return redirect(url_for('main.home'))

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM quiz_questions WHERE pdf_id = ? ORDER BY id", (pdf_id,))
    questions = cursor.fetchall()
    
    cursor.execute("SELECT course FROM uploaded_pdfs WHERE id = ? AND trial_id = ?", (pdf_id, trial['trial_id']))
    pdf_row = cursor.fetchone()
    conn.close()

    if not questions or not pdf_row:
        flash("Quiz questions not found.", "error")
        return redirect(url_for('trial.dashboard'))

    session["trial_score"] = 0
    session["trial_total"] = len(questions)
    session["trial_pdf_id"] = pdf_id
    session["trial_answered"] = []
    session["trial_start_time"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # 20 minutes timer
    end_time = datetime.datetime.now() + datetime.timedelta(minutes=20)
    session["trial_quiz_end_time"] = end_time.strftime("%Y-%m-%d %H:%M:%S")

    return redirect(url_for('trial.show_question', question_no=1))

@trial_bp.route('/quiz/question/<int:question_no>')
def show_question(question_no):
    trial = get_current_trial()
    if not trial:
        flash("Session expired.", "error")
        return redirect(url_for('main.home'))

    pdf_id = session.get("trial_pdf_id")
    if not pdf_id:
        return redirect(url_for('trial.dashboard'))

    # End time calculations
    end_time_str = session.get("trial_quiz_end_time")
    if not end_time_str:
        return redirect(url_for('trial.dashboard'))
        
    end_time = datetime.datetime.strptime(end_time_str, "%Y-%m-%d %H:%M:%S")
    remaining_seconds = max(int((end_time - datetime.datetime.now()).total_seconds()), 0)

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT course FROM uploaded_pdfs WHERE id = ? AND trial_id = ?",
        (pdf_id, trial['trial_id'])
    )
    course_row = cursor.fetchone()
    if not course_row:
        conn.close()
        flash("Access denied. This PDF is not part of your trial session.", "error")
        return redirect(url_for('trial.dashboard'))
    course_name = course_row["course"]

    if question_no <= 5:
        # Load Q1-5 from DB
        cursor.execute("SELECT * FROM quiz_questions WHERE pdf_id = ? ORDER BY id", (pdf_id,))
        questions = cursor.fetchall()
        conn.close()
        
        if not questions or len(questions) < question_no:
            flash("Question not found.", "error")
            return redirect(url_for('trial.dashboard'))
            
        question = questions[question_no - 1]
        
        return render_template(
            "trial_quiz.html",
            question=question,
            question_no=question_no,
            total_questions=10,
            pdf_id=pdf_id,
            course_name=course_name,
            timer=remaining_seconds,
            show_feedback=False,
            is_locked=False
        )
    else:
        # Questions 6-10 are LOCKED. No database query is made for question content!
        conn.close()
        return render_template(
            "trial_quiz.html",
            question=None,
            question_no=question_no,
            total_questions=10,
            pdf_id=pdf_id,
            course_name=course_name,
            timer=remaining_seconds,
            show_feedback=False,
            is_locked=True
        )

@trial_bp.route('/quiz/submit/<int:question_no>', methods=['POST'])
def submit_answer(question_no):
    trial = get_current_trial()
    if not trial:
        flash("Session expired.", "error")
        return redirect(url_for('main.home'))

    pdf_id = session.get("trial_pdf_id")
    if not pdf_id or question_no > 5:
        return redirect(url_for('trial.dashboard'))

    selected_answer = int(request.form.get("answer", -1))
    
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT course FROM uploaded_pdfs WHERE id = ? AND trial_id = ?",
        (pdf_id, trial['trial_id'])
    )
    course_row = cursor.fetchone()
    if not course_row:
        conn.close()
        flash("Access denied. This PDF is not part of your trial session.", "error")
        return redirect(url_for('trial.dashboard'))
    course_name = course_row["course"]

    # Load questions to compare
    cursor.execute("SELECT * FROM quiz_questions WHERE pdf_id = ? ORDER BY id", (pdf_id,))
    questions = cursor.fetchall()
    
    conn.close()

    if not questions or len(questions) < question_no:
        flash("Question not found.", "error")
        return redirect(url_for('trial.dashboard'))

    question = questions[question_no - 1]

    end_time_str = session.get("trial_quiz_end_time")
    if not end_time_str:
        return redirect(url_for('trial.dashboard'))
    end_time = datetime.datetime.strptime(end_time_str, "%Y-%m-%d %H:%M:%S")
    remaining_seconds = max(int((end_time - datetime.datetime.now()).total_seconds()), 0)

    # Time is up: stop accepting answers and finalize the trial quiz.
    if remaining_seconds <= 0:
        return redirect(url_for('trial.result_page', pdf_id=pdf_id))

    # Prevent duplicate scoring for an already-answered question.
    answered = session.setdefault("trial_answered", [])
    if question_no in answered:
        return redirect(url_for('trial.result_page', pdf_id=pdf_id))
    answered.append(question_no)
    session["trial_answered"] = answered

    is_correct = (selected_answer == question["correct_answer"])
    if is_correct:
        session["trial_score"] = session.get("trial_score", 0) + 1

    return render_template(
        "trial_quiz.html",
        question=question,
        question_no=question_no,
        total_questions=10,
        pdf_id=pdf_id,
        course_name=course_name,
        timer=remaining_seconds,
        show_feedback=True,
        is_correct=is_correct,
        selected_answer=selected_answer,
        next_question_no=question_no + 1
    )

@trial_bp.route('/result/<int:pdf_id>', methods=['GET', 'POST'])
def result_page(pdf_id):
    trial = get_current_trial()
    if not trial:
        flash("Session expired.", "error")
        return redirect(url_for('main.home'))

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT course FROM uploaded_pdfs WHERE id = ? AND trial_id = ?", (pdf_id, trial['trial_id']))
    pdf = cursor.fetchone()
    
    if not pdf:
        conn.close()
        flash("PDF details not found.", "error")
        return redirect(url_for('trial.dashboard'))

    # Finalize the trial exactly once: deduct credit and mark it used.
    if not trial['trial_used']:
        cursor.execute("""
            UPDATE guest_trials
            SET trial_used = 1, quiz_credit = 0, quiz_generated = 1
            WHERE trial_id = ?
        """, (trial['trial_id'],))
        conn.commit()
    conn.close()

    score = session.get("trial_score", 0)
    percentage = round((score / 5) * 100, 2)

    # Clean session
    session.pop("trial_quiz_end_time", None)
    session.pop("trial_answered", None)
    session.pop("trial_start_time", None)

    return render_template(
        "trial_result.html",
        score=score,
        total_questions=5,
        percentage=percentage,
        pdf_id=pdf_id,
        course=pdf['course']
    )

@trial_bp.route('/trial-used')
def trial_used_page():
    return render_template("trial_used.html")
