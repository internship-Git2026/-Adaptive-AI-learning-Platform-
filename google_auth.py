import logging
import os
import secrets

from flask import Blueprint, redirect, request, session, flash, url_for
from auth import verify_google_id_token
from database import get_db

logger = logging.getLogger(__name__)

google_auth_bp = Blueprint("google_auth", __name__, url_prefix="/auth")


def _client_id():
    return os.getenv("GOOGLE_CLIENT_ID", "").strip()


def _debug_mode():
    flag = os.getenv("GOOGLE_AUTH_DEBUG", "").strip().lower()
    if flag in ("1", "true", "yes"):
        return True
    flag = os.getenv("FLASK_DEBUG", "").strip().lower()
    return flag in ("1", "true", "yes")


def _peek_claims(token):
    """Decode a JWT payload WITHOUT verifying its signature (diagnostics only)."""
    try:
        import base64
        import json

        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return None


def _start_session(user):
    session["user_id"] = user["id"]
    session["user_name"] = user["name"]
    session["user_email"] = user["email"]


@google_auth_bp.route("/google", methods=["POST"])
def google_callback():
    """Shared Google sign-in/sign-up handler for both auth pages.

    The Google Identity Services button sends a verified ID token here. The
    behavior depends on the page that initiated the flow (`mode`):
      - signup: unknown emails auto-create an account and go to the plans page.
      - signin: unknown emails show a "no account found" error and are sent to
        sign-up instead (existing accounts are always signed in).
    """
    client_id = _client_id()
    if not client_id:
        flash("Google sign-in is not configured on this site.", "error")
        return redirect(url_for("signin.signin_page"))

    token = request.form.get("credential")
    mode = request.form.get("mode", "signin")
    if not token:
        flash("Google sign-in failed: no credential received. Please try again.", "error")
        return redirect(url_for("signin.signin_page"))

    try:
        info = verify_google_id_token(token, client_id)
    except Exception as exc:
        # Log the precise reason (type + message) so failures are diagnosable
        # from the server console; never show internals to the end user.
        logger.error(
            "GOOGLE_AUTH: token verification failed (%s): %s",
            type(exc).__name__, exc,
        )
        claims = _peek_claims(token)
        if claims:
            logger.error(
                "GOOGLE_AUTH: token claims aud=%s iss=%s email=%s "
                "email_verified=%s exp=%s iat=%s",
                claims.get("aud"), claims.get("iss"), claims.get("email"),
                claims.get("email_verified"), claims.get("exp"), claims.get("iat"),
            )
        if _debug_mode():
            flash(f"Google sign-in debug: {type(exc).__name__}: {exc}", "error")
        else:
            flash("Google sign-in could not verify your account. Please try again.", "error")
        return redirect(url_for("signin.signin_page"))

    email = info["email"]
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM users WHERE LOWER(email) = LOWER(?)", (email,))
    user = cursor.fetchone()

    if user:
        # Existing account -> sign in (works whether or not it was created
        # via Google; the email is Google-verified so it is the same person).
        if not user["google_id"]:
            cursor.execute(
                "UPDATE users SET google_id = ? WHERE id = ?",
                (info["google_sub"], user["id"]),
            )
            conn.commit()
        conn.close()
        logger.info("GOOGLE_AUTH: signed in existing user id=%s email=%s", user["id"], email)
        _start_session(user)
        return redirect(url_for("dashboard.dashboard_page"))

    # No account exists with this email yet.
    if mode != "signup":
        conn.close()
        logger.info("GOOGLE_AUTH: sign-in blocked (no account) email=%s", email)
        flash(
            "No account found with this Google email. Please create an account first.",
            "error",
        )
        return redirect(url_for("signup.signup_page"))

    # Sign-up flow -> auto-create the account. Google accounts have no usable
    # password, so store a random placeholder that can never match a typed one.
    placeholder_password = "!" + secrets.token_urlsafe(32)

    cursor.execute(
        """
        INSERT INTO users (
            name, email, password, selected_course, payment_plan,
            payment_status, trial_used, trial_credits, google_id
        )
        VALUES (?, ?, ?, NULL, NULL, 'NOT_PAID', 0, 1, ?)
        """,
        (info["name"], email, placeholder_password, info["google_sub"]),
    )
    new_user_id = cursor.lastrowid

    # Carry over any guest trial PDFs/quizzes the user created before signing up.
    trial_id = request.cookies.get("trial_id") or session.get("trial_id")
    if trial_id:
        cursor.execute("SELECT * FROM guest_trials WHERE trial_id = ?", (trial_id,))
        trial = cursor.fetchone()
        if trial:
            cursor.execute(
                "UPDATE uploaded_pdfs SET user_id = ? WHERE trial_id = ?",
                (new_user_id, trial_id),
            )
            cursor.execute(
                "UPDATE quiz_results SET user_id = ? WHERE trial_id = ?",
                (new_user_id, trial_id),
            )
            cursor.execute(
                "UPDATE guest_trials SET trial_used = 1 WHERE trial_id = ?",
                (trial_id,),
            )

    conn.commit()
    conn.close()

    logger.info("GOOGLE_AUTH: created new user id=%s email=%s", new_user_id, email)
    _start_session({"id": new_user_id, "name": info["name"], "email": email})
    flash("Account created with Google. Welcome aboard!", "success")
    return redirect(url_for("plans.plans_page"))