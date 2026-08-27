from flask import Blueprint, render_template, session, redirect, url_for
from database import get_db

# ==========================
# SETTINGS BLUEPRINT
# ==========================

settings_bp = Blueprint(
    "settings",
    __name__,
    url_prefix="/settings"
)

# ==========================
# SETTINGS PAGE
# ==========================

@settings_bp.route("/", methods=["GET"])
def settings_page():

    # Check Login
    user_email = session.get("user_email")

    if not user_email:
        return redirect(url_for("signin.signin_page"))

    conn = get_db()
    cursor = conn.cursor()

    # Get User Details
    cursor.execute(
        "SELECT * FROM users WHERE email=?",
        (user_email,)
    )

    user = cursor.fetchone()

    # User Not Found
    if not user:
        conn.close()
        session.clear()
        return redirect(url_for("signin.signin_page"))

    # Get Purchased Courses
    cursor.execute(
        """
        SELECT *
        FROM user_courses
        WHERE user_id=?
        """,
        (user["id"],)
    )

    courses = cursor.fetchall()

    conn.close()

    return render_template(
    "settings.html",
    user=user,
    courses=courses,
    selected_course=user["selected_course"]
)