from flask import Blueprint, render_template, request, redirect, url_for, session
from database import get_db
from auth import (
    verify_password,
    check_lockout,
    record_failed_attempt,
    reset_attempts
)

# ===== CREATE BLUEPRINT =====
signin_bp = Blueprint('signin', __name__, url_prefix='/signin')


# ===== SIGNIN PAGE ROUTE (GET) =====
@signin_bp.route('/', methods=['GET'])
def signin_page():
    return render_template('Signin_page.html')


# ===== SIGNIN FORM HANDLER (POST) =====
@signin_bp.route('/submit', methods=['POST'])
def signin_submit():

    # Get form data
    email = request.form.get('email', '').strip()
    password = request.form.get('password', '')
    ip = request.remote_addr or "unknown"

    # =========================================
    # 1. VALIDATE INPUT
    # =========================================

    if not email or not password:
        return render_template(
            'Signin_page.html',
            error="Email and password are required.",
            email=email
        ), 400

    # =========================================
    # 2. CHECK ACCOUNT/IP LOCKOUT
    # =========================================

    remaining = check_lockout(email, ip)

    if remaining > 0:
        minutes = max(1, int(remaining // 60) + 1)

        return render_template(
            'Signin_page.html',
            lockout=True,
            lockout_message=(
                f"Too many failed attempts. "
                f"Please try again in about {minutes} minute(s)."
            ),
            email=email
        ), 429

    # =========================================
    # 3. GET USER FROM DATABASE
    # =========================================

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT *
        FROM users
        WHERE email = ?
        """,
        (email,)
    )

    user = cursor.fetchone()

    conn.close()

    # =========================================
    # 4. VERIFY PASSWORD
    # =========================================

    if user and verify_password(user, password):

        # Successful login
        reset_attempts(email, ip)

        # Store user information in session
        session["user_id"] = user["id"]
        session["user_name"] = user["name"]
        session["user_email"] = user["email"]

        # Redirect to dashboard
        return redirect(
            url_for('dashboard.dashboard_page')
        )

    # =========================================
    # 5. INCORRECT EMAIL/PASSWORD
    # =========================================

    remaining_after_failure = record_failed_attempt(email, ip)

    # =========================================
    # 6. CHECK IF THIS FAILURE CAUSED LOCKOUT
    # =========================================

    if remaining_after_failure > 0:
        minutes = max(
            1,
            int(remaining_after_failure // 60) + 1
        )

        return render_template(
            'Signin_page.html',
            lockout=True,
            lockout_message=(
                f"Too many failed attempts. "
                f"Please try again in about {minutes} minute(s)."
            ),
            email=email
        ), 429

    # =========================================
    # 7. NORMAL INCORRECT PASSWORD MESSAGE
    # =========================================

    return render_template(
        'Signin_page.html',
        error="Incorrect email or password.",
        email=email
    ), 401


# ===== GOOGLE SIGNIN HANDLER =====
# Add your Google signin route here if required.


# ===== SIGNUP LINK HANDLER =====
@signin_bp.route('/signup-page', methods=['GET'])
def signup_page():
    return redirect(url_for('signup.signup_page'))