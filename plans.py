from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from database import get_db
from datetime import datetime
from course_access import COURSES, PRICE_MAP, grant_course

plans_bp = Blueprint('plans', __name__, url_prefix='/plans')

@plans_bp.route('/', methods=['GET', 'POST'])
def plans_page():
    """Render plans / checkout page and handle simulated subscription purchase"""
    user_email = session.get("user_email")
    if not user_email:
        flash("Please sign up or sign in to choose a course plan.", "info")
        return redirect(url_for('signin.signin_page'))

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE email = ?", (user_email,))
    user = cursor.fetchone()

    if not user:
        conn.close()
        session.clear()
        return redirect(url_for('signin.signin_page'))

    if request.method == 'POST':
        selected_course = request.form.get('selected_course')
        if selected_course not in PRICE_MAP:
            conn.close()
            flash("Invalid course selection.", "error")
            return redirect(url_for('plans.plans_page'))

        payment_plan = PRICE_MAP[selected_course]
        enrolled_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Simulate successful payment: update payment_status to PAID
        cursor.execute("""
            UPDATE users
            SET selected_course = ?,
                payment_plan = ?,
                payment_status = 'PAID',
                enrolled_at = ?
            WHERE email = ?
        """, (selected_course, payment_plan, enrolled_at, user_email))

        # Record the verified purchase so entitlement is backed by user_courses
        grant_course(user["id"], selected_course, payment_plan, conn=conn, cursor=cursor)

        conn.commit()
        conn.close()

        flash(f"Simulated Payment Successful! You are now enrolled in {selected_course}.", "success")
        return redirect(url_for('dashboard.dashboard_page'))

    # Preselect a course when arriving from the enroll / add-course flows
    preselected = request.args.get('course')
    if preselected not in COURSES:
        preselected = user['selected_course']

    conn.close()
    return render_template('plans.html', user=user, selected_course=preselected)
