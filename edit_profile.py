from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from database import get_db
from activity import add_activity
import re

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# ==========================
# BLUEPRINT
# ==========================

edit_profile_bp = Blueprint(
    "edit_profile",
    __name__,
    url_prefix="/edit-profile"
)

# ==========================
# EDIT PROFILE PAGE
# ==========================

@edit_profile_bp.route("/", methods=["GET", "POST"])
def edit_profile():

    user_email = session.get("user_email")

    if not user_email:
        return redirect(url_for("signin.signin_page"))

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM users WHERE email=?",
        (user_email,)
    )

    user = cursor.fetchone()

    if request.method == "POST":

        name = request.form.get("name")
        email = request.form.get("email")
        phone = request.form.get("phone")
        college = request.form.get("college")
        department = request.form.get("department")
        year = request.form.get("year")

        if not name or not name.strip():
            flash("Name cannot be empty.", "error")
            return redirect(url_for("edit_profile.edit_profile"))

        if not email or not EMAIL_RE.match(email.strip()):
            flash("Please enter a valid email address.", "error")
            return redirect(url_for("edit_profile.edit_profile"))

        email = email.strip()

        # Prevent taking over another account's email address
        cursor.execute(
            "SELECT id FROM users WHERE LOWER(email) = LOWER(?) AND id != ?",
            (email, user["id"])
        )
        if cursor.fetchone():
            conn.close()
            flash("That email is already registered to another account.", "error")
            return redirect(url_for("edit_profile.edit_profile"))

        cursor.execute("""
            UPDATE users
            SET
                name=?,
                email=?,
                phone=?,
                college=?,
                department=?,
                year=?
            WHERE id=?
        """, (
            name,
            email,
            phone,
            college,
            department,
            year,
            user["id"]
        ))

        conn.commit()

        add_activity(
            user["id"],
            "profile",
            "Profile Updated",
            "Personal information updated"
        )

        session["user_email"] = email

        flash("Profile updated successfully!", "success")

        conn.close()

        return redirect(url_for("profile.profile_page"))

    conn.close()

    return render_template(
        "edit_profile.html",
        user=user,
        active_page="profile"
    )