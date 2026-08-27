from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from database import get_db
from course_access import has_course_access

quiz_bp = Blueprint('quiz', __name__, url_prefix='/ai-quiz')

@quiz_bp.route('/', methods=['GET', 'POST'])
def ai_quiz():
    """Render the AI quiz page with trial and payment gating"""
    user_email = session.get("user_email")
    
    # Retrieve course context (default to GATE)
    course_theme = request.args.get('course', 'GATE').upper()
    if course_theme not in ['GATE', 'NEET']:
        course_theme = 'GATE'

    # Check database status if user is logged in
    if user_email:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE email = ?", (user_email,))
        user = cursor.fetchone()

        if not user:
            conn.close()
            session.clear()
            return redirect(url_for('signin.signin_page'))

        trial_credits = user['trial_credits']
        payment_status = user['payment_status']

        # 1. Check if trial credit is available
        if trial_credits > 0:
            cursor.execute("""
                UPDATE users
                SET trial_credits = 0, trial_used = 1
                WHERE email = ?
            """, (user_email,))
            conn.commit()
            conn.close()
            return render_template('quiz.html', user=user, course_theme=course_theme, trial_status="FREE_TRIAL_ACTIVE")
        
        # 2. Check if course is paid
        elif payment_status == 'PAID':
            # Check if enrolled in this course or combo via a verified purchase record
            if has_course_access(user['id'], course_theme):
                conn.close()
                return render_template('quiz.html', user=user, course_theme=course_theme, trial_status="PAID_ACCESS")
            else:
                conn.close()
                flash(f"You do not have access to {course_theme} course quizzes. Please enroll or upgrade first.", "warning")
                return redirect(url_for('my_courses.my_courses_page'))
        else:
            conn.close()
            # Logged-in unpaid users are blocked if trial is used
            flash("Your free trial has ended. Please purchase a course to continue.", "info")
            return redirect(url_for('plans.plans_page'))

    # Guest user logic
    else:
        trial_credits = session.get("trial_credits", 1)
        if trial_credits > 0:
            session["trial_credits"] = 0
            session["trial_used"] = 1
            return render_template('quiz.html', user=None, course_theme=course_theme, trial_status="FREE_TRIAL_ACTIVE")
        else:
            return render_template('quiz.html', user=None, course_theme=course_theme, trial_status="TRIAL_ENDED")