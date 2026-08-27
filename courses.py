from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from database import get_db
from course_access import COURSES, has_course_access, get_purchased_courses

courses_bp = Blueprint('courses', __name__)

@courses_bp.route('/dashboard/courses')
def courses_list_page():
    user_email = session.get("user_email")
    if not user_email:
        return redirect(url_for('signin.signin_page'))

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE email = ?", (user_email,))
    user = cursor.fetchone()

    if not user or user['payment_status'] != 'PAID':
        conn.close()
        return redirect(url_for('plans.plans_page'))

    purchased_courses = get_purchased_courses(user['id'])
    conn.close()

    return render_template('courses.html', user=user, purchased_courses=purchased_courses)


@courses_bp.route('/dashboard/enroll', methods=['POST'])
def enroll_course_submit():
    user_email = session.get("user_email")
    if not user_email:
        return redirect(url_for('signin.signin_page'))

    selected_course = request.form.get('selected_course')
    if selected_course not in COURSES:
        flash("Invalid course selection.", "error")
        return redirect(url_for('courses.courses_list_page'))

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE email = ?", (user_email,))
    user = cursor.fetchone()

    if not user:
        conn.close()
        session.clear()
        return redirect(url_for('signin.signin_page'))

    # Entitlement only comes from a verified purchase record (user_courses).
    # Course selection alone must never grant paid access.
    if not has_course_access(user['id'], selected_course):
        conn.close()
        flash(f"Please complete payment to enroll in {selected_course}.", "info")
        return redirect(url_for('plans.plans_page', course=selected_course))

    # Course already purchased: update the active course pointer only.
    cursor.execute("""
        UPDATE users
        SET selected_course = ?
        WHERE email = ?
    """, (selected_course, user_email))
    conn.commit()

    conn.close()

    flash(f"{selected_course} is now your active course.", "success")
    return redirect(url_for('my_courses.my_courses_page'))
