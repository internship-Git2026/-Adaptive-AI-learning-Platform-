from flask import Blueprint, render_template, request, redirect, url_for, session
from database import get_db
from auth import hash_password, check_lockout, record_ip_activity

# ===== CREATE BLUEPRINT =====
signup_bp = Blueprint('signup', __name__, url_prefix='/signup')

# ===== SIGNUP PAGE ROUTE =====
@signup_bp.route('/', methods=['GET'])
def signup_page():
    return render_template('Signup_page.html')


# ===== SIGNUP FORM HANDLER =====
@signup_bp.route('/signup_button', methods=['POST'])
def signup_button():

    # Get form data
    name = request.form.get('name')
    email = request.form.get('email')
    password = request.form.get('password')
    confirm_password = request.form.get('confirm_password')
    selected_course = request.form.get('course')  # GATE, NEET, GATE+NEET
    ip = request.remote_addr or "unknown"

    # Brute-force / mass-signup throttle per IP
    if check_lockout("signup", ip) > 0:
        return "Too many signup attempts from this network. Please try again later.", 429

    # ===== VALIDATION =====
    if password != confirm_password:
        record_ip_activity(ip)
        return "Passwords do not match!", 400

    if len(password) < 8:
        record_ip_activity(ip)
        return "Password must be at least 8 characters long!", 400

    if not selected_course or selected_course not in ['GATE', 'NEET', 'GATE+NEET']:
        record_ip_activity(ip)
        return "Please select a valid course!", 400

    price_map = {
        'GATE': 1000,
        'NEET': 1000,
        'GATE+NEET': 1500
    }
    payment_plan = price_map[selected_course]

    conn = get_db()
    cursor = conn.cursor()

    # Check if email already exists
    cursor.execute(
        "SELECT * FROM users WHERE email = ?",
        (email,)
    )

    existing_user = cursor.fetchone()

    if existing_user:
        conn.close()
        record_ip_activity(ip)
        return "Email already registered!", 400

    # Insert user with selected course and NOT_PAID status
    cursor.execute(
        """
        INSERT INTO users (name, email, password, selected_course, payment_plan, payment_status, trial_used, trial_credits)
        VALUES (?, ?, ?, ?, ?, 'NOT_PAID', 0, 1)
        """,
        (name, email, hash_password(password), selected_course, payment_plan)
    )
    new_user_id = cursor.lastrowid

    # Support Guest Trial data transfer
    trial_id = request.cookies.get("trial_id") or session.get("trial_id")
    if trial_id:
        cursor.execute("SELECT * FROM guest_trials WHERE trial_id = ?", (trial_id,))
        trial = cursor.fetchone()
        if trial:
            cursor.execute("UPDATE uploaded_pdfs SET user_id = ? WHERE trial_id = ?", (new_user_id, trial_id))
            cursor.execute("UPDATE quiz_results SET user_id = ? WHERE trial_id = ?", (new_user_id, trial_id))
            cursor.execute("UPDATE guest_trials SET trial_used = 1 WHERE trial_id = ?", (trial_id,))

    conn.commit()
    conn.close()

    # Count successful signups against the per-IP throttle
    record_ip_activity(ip)

    # Save user into session to log them in
    session["user_id"] = new_user_id
    session["user_name"] = name
    session["user_email"] = email

    # Redirect to plan confirmation page instead of dashboard
    return redirect(url_for('plans.plans_page'))