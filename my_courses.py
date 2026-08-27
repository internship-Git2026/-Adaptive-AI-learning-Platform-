from flask import Blueprint, render_template, redirect, url_for, session, flash
from database import get_db
from course_access import get_purchased_courses

my_courses_bp = Blueprint('my_courses', __name__, url_prefix='/dashboard/my-courses')


def get_course_progress(user_id, course):
    """Overall quiz-based progress (correct answers / total questions) for one course."""
    conn = get_db()
    row = conn.execute("""
        SELECT COALESCE(SUM(qr.score), 0) AS total_score,
               COALESCE(SUM(qr.total_questions), 0) AS total_questions
        FROM quiz_results qr
        JOIN uploaded_pdfs p ON qr.pdf_id = p.id
        WHERE qr.user_id = ? AND p.course = ?
    """, (user_id, course)).fetchone()
    conn.close()
    if not row or not row["total_questions"]:
        return 0
    return round((row["total_score"] / row["total_questions"]) * 100)

@my_courses_bp.route('/')
def my_courses_page():
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

    user_id = user['id']

    # Entitlement comes from verified purchase records (user_courses)
    purchased_courses = get_purchased_courses(user_id)

    if not purchased_courses:
        conn.close()
        flash("Please purchase a course first!", "warning")
        return redirect(url_for('plans.plans_page'))

    selected_course = user['selected_course']

    # Query GATE PDFs
    cursor.execute("""
        SELECT * FROM uploaded_pdfs 
        WHERE user_id = ? AND course = 'GATE' 
        ORDER BY upload_time DESC
    """, (user_id,))
    gate_pdfs = [dict(row) for row in cursor.fetchall()]
    
    # Query NEET PDFs
    cursor.execute("""
        SELECT * FROM uploaded_pdfs 
        WHERE user_id = ? AND course = 'NEET' 
        ORDER BY upload_time DESC
    """, (user_id,))
    neet_pdfs = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    
    # Process stats for GATE
    gate_stats = {
        'total': len(gate_pdfs),
        'latest_name': gate_pdfs[0]['pdf_name'] if gate_pdfs else "None",
        'latest_date': gate_pdfs[0]['upload_time'] if gate_pdfs else "N/A"
    }
    
    # Process stats for NEET
    neet_stats = {
        'total': len(neet_pdfs),
        'latest_name': neet_pdfs[0]['pdf_name'] if neet_pdfs else "None",
        'latest_date': neet_pdfs[0]['upload_time'] if neet_pdfs else "N/A"
    }

    # Real course progress from quiz results (per course)
    gate_progress = get_course_progress(user_id, 'GATE')
    neet_progress = get_course_progress(user_id, 'NEET')

    return render_template(
        'my_courses.html', 
        user=user, 
        selected_course=selected_course,
        purchased_courses=purchased_courses,
        gate_pdfs=gate_pdfs,
        neet_pdfs=neet_pdfs,
        gate_stats=gate_stats,
        neet_stats=neet_stats,
        gate_progress=gate_progress,
        neet_progress=neet_progress
    )
