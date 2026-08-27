from flask import Blueprint, render_template, redirect, url_for, session, flash
from database import get_db
from course_access import has_course_access
from gate_course import get_neet_subject_progress

neet_course_bp = Blueprint('neet_course', __name__, url_prefix='/dashboard/neet')

@neet_course_bp.route('/')
def neet_course_page():
    user_email = session.get("user_email")
    if not user_email:
        return redirect(url_for('signin.signin_page'))

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE email = ?", (user_email,))
    user = cursor.fetchone()
    conn.close()

    if not user or user['payment_status'] != 'PAID':
        return redirect(url_for('plans.plans_page'))

    if not has_course_access(user['id'], 'NEET'):
        flash("You are not enrolled in the NEET course. Please purchase the course to access.", "warning")
        return redirect(url_for('my_courses.my_courses_page'))

    subjects = get_neet_subject_progress(user['id'])

    return render_template('neet_course.html', subjects=subjects)
