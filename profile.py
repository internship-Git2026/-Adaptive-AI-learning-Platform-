import os
import uuid
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, send_file, abort
from database import get_db
from datetime import datetime
from werkzeug.utils import secure_filename
import re

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# ==========================
# CREATE BLUEPRINT
# ==========================

profile_bp = Blueprint(
    'profile',
    __name__,
    url_prefix='/profile'
)

def format_activity_time(activity_time):

    try:

        activity_time = datetime.strptime(
            activity_time,
            "%Y-%m-%d %H:%M:%S"
        )

        now = datetime.now()

        diff = now - activity_time

        seconds = diff.total_seconds()

        if seconds < 60:
            return "Just now"

        elif seconds < 3600:
            minutes = int(seconds // 60)
            return f"{minutes} min ago"

        elif seconds < 86400:
            hours = int(seconds // 3600)
            return f"{hours} hr ago"

        elif seconds < 172800:
            return "Yesterday"

        else:
            return activity_time.strftime("%d %b %Y")

    except Exception:

        return str(activity_time)


# ==========================
# PROFILE PAGE
# ==========================

@profile_bp.route('/', methods=['GET'])
def profile_page():

    user_email = session.get("user_email")

    if not user_email:
        flash("Please log in first.", "info")
        return redirect(url_for('signin.signin_page'))

    conn = get_db()
    cursor = conn.cursor()

    # ---------------- USER DETAILS ---------------- #

    cursor.execute(
        "SELECT * FROM users WHERE email=?",
        (user_email,)
    )

    user = cursor.fetchone()

    if not user:
        conn.close()
        session.clear()
        return redirect(url_for('signin.signin_page'))

    user_id = user["id"]

    # ================= USER COURSES =================

    cursor.execute("""
        SELECT *
        FROM user_courses
        WHERE user_id=?
    """, (user_id,))

    courses = cursor.fetchall()

    # =========================================================
    # TOTAL PDF UPLOADED
    # =========================================================

    cursor.execute("""
        SELECT COUNT(*) AS total
        FROM uploaded_pdfs
        WHERE user_id=?
    """, (user_id,))

    pdfs_uploaded = cursor.fetchone()["total"]

    # =========================================================
    # TOTAL QUIZZES
    # =========================================================

    cursor.execute("""
        SELECT COUNT(*) AS total
        FROM quiz_results
        WHERE user_id=?
    """, (user_id,))

    ai_quizzes = cursor.fetchone()["total"]

    # =========================================================
    # QUESTIONS SOLVED
    # =========================================================

    cursor.execute("""
        SELECT SUM(total_questions) AS total
        FROM quiz_results
        WHERE user_id=?
    """, (user_id,))

    row = cursor.fetchone()

    questions_solved = row["total"] if row["total"] else 0

    # =========================================================
    # ACCURACY
    # =========================================================

    cursor.execute("""
        SELECT AVG(percentage) AS average
        FROM quiz_results
        WHERE user_id=?
    """, (user_id,))

    row = cursor.fetchone()

    accuracy = round(row["average"]) if row["average"] else 0

    # =========================================================
    # STUDY HOURS
    # =========================================================

    cursor.execute("SELECT SUM(duration_minutes) as total_min FROM study_sessions WHERE user_id = ?", (user_id,))
    study_row = cursor.fetchone()
    total_minutes = study_row['total_min'] if study_row and study_row['total_min'] else 0
    study_hours = round(total_minutes / 60.0, 1)

# =========================================================
# RECENT ACTIVITY
# =========================================================

    cursor.execute("""
      SELECT *
      FROM recent_activity
      WHERE user_id=?
      ORDER BY activity_time DESC
      LIMIT 5
    """, (user_id,))

    activities = cursor.fetchall()

    ICON_MAP = {
      "pdf": "fa-file-pdf",
      "quiz": "fa-robot",
      "profile": "fa-user-pen",
      "course": "fa-book",
      "practice": "fa-pencil"
    }

    COLOR_MAP = {
      "pdf": "pdf-color",
      "quiz": "quiz-color",
      "profile": "profile-color",
      "course": "course-color",
      "practice": "practice-color"
    }

    recent_activity = []

    for activity in activities:

      recent_activity.append({

        "title": activity["activity_title"],

        "description": activity["activity_description"],

        "time": format_activity_time(
          activity["activity_time"]
        ),

        "icon": ICON_MAP.get(
            activity["activity_type"],
            "fa-circle"
        ),

        "color": COLOR_MAP.get(
            activity["activity_type"],
            "default-color"
        )

    })

    selected_course = user["selected_course"] if user["selected_course"] else "None Selected"
    payment_status = user["payment_status"]

    # AI Doubt Solver Stats
    # 1. Questions Asked
    cursor.execute("SELECT COUNT(*) FROM ai_doubt_history WHERE user_id=?", (user_id,))
    questions_asked = cursor.fetchone()[0] or 0

    # 2. Most Asked Subject
    cursor.execute("""
        SELECT subject, COUNT(subject) as cnt 
        FROM ai_doubt_history 
        WHERE user_id=? AND subject != 'General'
        GROUP BY subject 
        ORDER BY cnt DESC 
        LIMIT 1
    """, (user_id,))
    sub_row = cursor.fetchone()
    most_asked_subject = sub_row[0] if sub_row else "None"

    # 3. Most Viewed PDF
    cursor.execute("""
        SELECT pdf_name, COUNT(pdf_name) as cnt 
        FROM ai_doubt_history 
        WHERE user_id=? AND pdf_name != 'N/A'
        GROUP BY pdf_name 
        ORDER BY cnt DESC 
        LIMIT 1
    """, (user_id,))
    pdf_row = cursor.fetchone()
    most_viewed_pdf = pdf_row[0] if pdf_row else "None"

    # 4. Learning Trend (questions this week)
    cursor.execute("""
        SELECT COUNT(*) 
        FROM ai_doubt_history 
        WHERE user_id=? AND created_at >= datetime('now', '-7 days')
    """, (user_id,))
    weekly_doubts = cursor.fetchone()[0] or 0
    learning_trend = f"+{weekly_doubts} doubts this week"

    conn.close()

    return render_template(

        "profile.html",

        fullname=user["name"],

        email=user["email"],



        department=user["department"],

        year=user["year"],  

        joined=user["enrolled_at"] if user["enrolled_at"] else "Not Enrolled",

        selected_course=selected_course,

        payment_status=payment_status,

        pdfs_uploaded=pdfs_uploaded,

        ai_quizzes=ai_quizzes,

        questions_solved=questions_solved,

        accuracy=accuracy,

        study_hours=study_hours,

        recent_activity=recent_activity,

        courses=courses,

        user=user,

        questions_asked=questions_asked,

        most_asked_subject=most_asked_subject,

        most_viewed_pdf=most_viewed_pdf,

        learning_trend=learning_trend,

        active_page="profile"
    )


# ==========================
# UPDATE PROFILE
# ==========================

@profile_bp.route('/update_profile', methods=['POST'])
def update_profile():

    user_email = session.get("user_email")

    if not user_email:
        return redirect(url_for('signin.signin_page'))

    fullname = request.form.get("fullname")

    email = request.form.get("email")

    if not fullname or not fullname.strip():
        flash("Name cannot be empty.", "error")
        return redirect(url_for('profile.profile_page'))

    if not email or not EMAIL_RE.match(email.strip()):
        flash("Please enter a valid email address.", "error")
        return redirect(url_for('profile.profile_page'))

    email = email.strip()

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT id FROM users WHERE email = ?",
        (user_email,)
    )
    me = cursor.fetchone()

    if not me:
        conn.close()
        session.clear()
        return redirect(url_for('signin.signin_page'))

    # Prevent taking over another account's email address
    cursor.execute(
        "SELECT id FROM users WHERE LOWER(email) = LOWER(?) AND id != ?",
        (email, me['id'])
    )
    if cursor.fetchone():
        conn.close()
        flash("That email is already registered to another account.", "error")
        return redirect(url_for('profile.profile_page'))

    cursor.execute("""
        UPDATE users
        SET
            name=?,
            email=?
        WHERE
            email=?
    """, (fullname, email, user_email))

    conn.commit()
    conn.close()

    session["user_name"] = fullname
    session["user_email"] = email

    flash("Profile updated successfully!", "success")

    return redirect(url_for('profile.profile_page'))


# ==========================
# PROFILE PHOTO
# ==========================

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
MAX_PHOTO_SIZE = 5 * 1024 * 1024  # 5 MB


def _photo_dir():
    """Return the uploads directory for profile photos."""
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
    os.makedirs(d, exist_ok=True)
    return d


def _find_photo(user_id):
    """Find existing profile photo file for a user, or None."""
    d = _photo_dir()
    for ext in ALLOWED_EXTENSIONS:
        path = os.path.join(d, f'profile_{user_id}.{ext}')
        if os.path.isfile(path):
            return path
    return None


@profile_bp.route('/photo/<int:user_id>')
def serve_photo(user_id):
    """Serve the user's profile photo."""
    path = _find_photo(user_id)
    if not path:
        abort(404)
    return send_file(path)


@profile_bp.route('/upload-photo', methods=['POST'])
def upload_photo():
    """Upload a profile photo. Stored as profile_<user_id>.<ext> in uploads/."""
    user_email = session.get('user_email')
    if not user_email:
        return redirect(url_for('signin.signin_page'))

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT id FROM users WHERE email = ?', (user_email,))
    user = cursor.fetchone()
    conn.close()

    if not user:
        session.clear()
        return redirect(url_for('signin.signin_page'))

    user_id = user['id']

    if 'photo' not in request.files:
        flash('No file selected.', 'error')
        return redirect(url_for('profile.profile_page'))

    file = request.files['photo']
    if file.filename == '':
        flash('No file selected.', 'error')
        return redirect(url_for('profile.profile_page'))

    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in ALLOWED_EXTENSIONS:
        flash('Unsupported file type. Please upload PNG, JPG, GIF, or WebP.', 'error')
        return redirect(url_for('profile.profile_page'))

    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    if size > MAX_PHOTO_SIZE:
        flash('File too large. Maximum size is 5 MB.', 'error')
        return redirect(url_for('profile.profile_page'))

    # Delete old photo
    old = _find_photo(user_id)
    if old:
        try:
            os.remove(old)
        except OSError:
            pass

    # Save new photo
    filename = f'profile_{user_id}.{ext}'
    filepath = os.path.join(_photo_dir(), filename)
    file.save(filepath)

    flash('Profile photo updated!', 'success')
    return redirect(url_for('profile.profile_page'))


@profile_bp.route('/delete-photo', methods=['POST'])
def delete_photo():
    """Delete the user's profile photo."""
    user_email = session.get('user_email')
    if not user_email:
        return redirect(url_for('signin.signin_page'))

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT id FROM users WHERE email = ?', (user_email,))
    user = cursor.fetchone()
    conn.close()

    if not user:
        session.clear()
        return redirect(url_for('signin.signin_page'))

    old = _find_photo(user['id'])
    if old:
        try:
            os.remove(old)
            flash('Profile photo removed.', 'success')
        except OSError:
            flash('Could not remove photo.', 'error')
    else:
        flash('No photo to remove.', 'info')

    return redirect(url_for('profile.profile_page'))