import os
import secrets
from flask import Flask, render_template, redirect, url_for, request, session, flash, Blueprint, abort
from database import get_db, create_tables
from dotenv import load_dotenv

# Load environment variables from .env BEFORE importing blueprints so that
# modules which read them at import time (e.g. doubt_solver reads GROQ_API_KEY
# for the Groq client) see the values from .env.
load_dotenv()

# ===== IMPORT BLUEPRINTS =====
from Signin_page import signin_bp 
from Signup_Page import signup_bp
from profile import profile_bp
from Dashboard_Page import dashboard_bp
from plans import plans_bp
from quiz import quiz_bp
from gate_course import gate_course_bp
from neet_course import neet_course_bp
from my_courses import my_courses_bp
from courses import courses_bp
from pdf_upload import pdf_upload_bp
from ai_quiz import ai_quiz_bp
from settings import settings_bp
from edit_profile import edit_profile_bp
from add_course import add_course_bp
from progress import progress_bp
from trial import trial_bp
from notification_rout import notification_bp
from doubt_solver import doubt_solver_bp
from practice import practice_bp
from google_auth import google_auth_bp

app = Flask(__name__)

# Fail fast at startup if any required environment variable is missing.
# Only the variable names are reported here - never their values.
required_vars = ["GROQ_API_KEY", "SECRET_KEY"]
missing_vars = [
    variable for variable in required_vars if not os.getenv(variable)
]
if missing_vars:
    raise RuntimeError(
        "Missing required environment variables: "
        + ", ".join(missing_vars)
        + ". Configure them in the .env file before starting the application."
    )

# Session signing key: MUST come from .env for stable sessions across
# restarts. A missing SECRET_KEY is a startup error (validated above); a
# random fallback would silently invalidate sessions on every restart.
app.secret_key = os.getenv("SECRET_KEY")
app.config["SECRET_KEY"] = app.secret_key
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# Authoritative upload directory. The database stores only the portable
# filename; the real filesystem path is built from this value at runtime
# (see pdf_storage.get_pdf_path).
app.config["UPLOAD_FOLDER"] = os.path.join(app.root_path, "uploads")
# Only send the session cookie over HTTPS in production
if os.getenv("SESSION_COOKIE_SECURE", "").lower() in ("1", "true", "yes"):
    app.config["SESSION_COOKIE_SECURE"] = True

# Behind a reverse proxy, trust N proxy hops so request.remote_addr and
# request.scheme reflect the real client (keeps brute-force IP tracking valid).
# Set TRUSTED_PROXIES=1 when running behind a single proxy (nginx/caddy/etc.).
trusted_proxies = int(os.getenv("TRUSTED_PROXIES", "0") or 0)
if trusted_proxies > 0:
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=trusted_proxies, x_proto=1, x_host=1)

# ===== CSRF PROTECTION =====
def get_csrf_token():
    """Return the session's CSRF token, generating one on first use."""
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_hex(32)
        session["_csrf_token"] = token
    return token


@app.before_request
def csrf_protect():
    """Reject state-changing requests without a valid CSRF token."""
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        expected = session.get("_csrf_token")
        submitted = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
        if not expected or not submitted or not secrets.compare_digest(expected, submitted):
            abort(400)


@app.context_processor
def inject_csrf_token():
    return {"csrf_token": get_csrf_token}


@app.context_processor
def inject_google_config():
    """Expose Google sign-in config to templates (empty when not configured)."""
    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    return {
        "GOOGLE_CLIENT_ID": client_id,
        "google_auth_enabled": bool(client_id),
    }

# ===== MAIN BLUEPRINT (Home & Logout) =====
main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def home():
    """Render the main landing page"""
    user_email = session.get("user_email")
    user = None
    if user_email:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE email = ?", (user_email,))
        user = cursor.fetchone()
        conn.close()
    return render_template('Main_page.html', user=user)


@main_bp.route('/logout')
def logout():
    """Clear session and logout user"""
    session.clear()
    flash("You have been signed out.", "success")
    return redirect(url_for('main.home'))

# ===== REGISTER BLUEPRINTS =====
app.register_blueprint(main_bp)
app.register_blueprint(signin_bp)
app.register_blueprint(dashboard_bp)
app.register_blueprint(signup_bp)
app.register_blueprint(profile_bp)
app.register_blueprint(plans_bp)
app.register_blueprint(quiz_bp)
app.register_blueprint(gate_course_bp)
app.register_blueprint(neet_course_bp)
app.register_blueprint(my_courses_bp)
app.register_blueprint(courses_bp)
app.register_blueprint(pdf_upload_bp)
app.register_blueprint(ai_quiz_bp)
app.register_blueprint(settings_bp)
app.register_blueprint(edit_profile_bp)
app.register_blueprint(add_course_bp)
app.register_blueprint(progress_bp)
app.register_blueprint(trial_bp)
app.register_blueprint(notification_bp)
app.register_blueprint(doubt_solver_bp)
app.register_blueprint(practice_bp)
app.register_blueprint(google_auth_bp)

@app.context_processor
def inject_notifications():
    if "user_id" in session:
        from notifications import get_unread_count
        return {"unread_notifications_count": get_unread_count(session["user_id"])}
    return {"unread_notifications_count": 0}

create_tables()

if __name__ == '__main__':
    # Enable debug only via FLASK_DEBUG=1; never in production
    debug = os.getenv("FLASK_DEBUG", "").lower() in ("1", "true", "yes")
    app.run(debug=debug)