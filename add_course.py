from flask import Blueprint, render_template, session, redirect, url_for
from database import get_db

add_course_bp = Blueprint(
    "add_course",
    __name__,
    url_prefix="/add-course"
)

@add_course_bp.route("/")
def add_course():

    user_email = session.get("user_email")

    if not user_email:
        return redirect(url_for("signin.signin_page"))

    conn = get_db()
    cursor = conn.cursor()

    # Logged in user
    cursor.execute(
        "SELECT * FROM users WHERE email=?",
        (user_email,)
    )

    user = cursor.fetchone()

    # Courses already purchased
    cursor.execute(
        "SELECT * FROM user_courses WHERE user_id=?",
        (user["id"],)
    )

    my_courses = cursor.fetchall()

    owned_course_names = {c["course_name"] for c in my_courses}

    conn.close()

    return render_template(
        "add_course.html",
        user=user,
        my_courses=my_courses,
        owned_course_names=owned_course_names
    )