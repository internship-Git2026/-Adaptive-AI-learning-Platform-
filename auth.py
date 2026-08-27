from datetime import datetime, timedelta
from database import get_db
from werkzeug.security import generate_password_hash, check_password_hash
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

# Legacy rows predate hashing and store the plaintext password directly.
# We still verify them but upgrade them to a hash on first successful login.
HASH_PREFIXES = ("scrypt:", "pbkdf2:", "sha256:")

# ---- Brute-force lockout settings ----
LOCKOUT_MAX_ACCOUNT = 5     # failures per account per IP
LOCKOUT_MAX_IP = 20         # failures per IP across all accounts
LOCKOUT_SECONDS = 900       # 15 minute lockout
LOCKOUT_WINDOW = 900        # 15 minute sliding window
TIME_FMT = "%Y-%m-%d %H:%M:%S"


def hash_password(password):
    return generate_password_hash(password)


def verify_password(user, password):
    """Verify a password against the stored credential.

    Supports hashed rows and legacy plaintext rows (auto-upgraded on success).
    """
    stored = user["password"]
    if stored.startswith(HASH_PREFIXES):
        return check_password_hash(stored, password)

    if stored == password:
        conn = get_db()
        conn.execute(
            "UPDATE users SET password = ? WHERE id = ?",
            (hash_password(password), user["id"]),
        )
        conn.commit()
        conn.close()
        return True

    return False


def verify_google_id_token(token, client_id):
    """Verify a Google Identity Services ID token and return its profile.

    Returns a dict: {email, name, google_sub}. Raises ValueError if the token
    is malformed, expired, signed by someone else, issued for a different
    audience/client, or if the email is not verified.
    """
    if not token or not client_id:
        raise ValueError("Missing Google token or client id.")

    info = id_token.verify_oauth2_token(
        token,
        google_requests.Request(),
        client_id,
        # Tolerate modest clock drift between this server and Google's signer.
        # The library's default of 0 rejects tokens whose `iat` is a few
        # seconds "in the future" when machine clocks are slightly behind.
        clock_skew_in_seconds=300,
    )

    email = info.get("email") or ""
    if not email:
        raise ValueError("Google token did not contain an email claim.")
    if info.get("email_verified") not in (True, "true"):
        raise ValueError("Google account email is not verified.")

    sub = info.get("sub")
    if not sub:
        raise ValueError("Google token did not contain a subject claim.")

    return {
        "email": email.lower(),
        "name": (info.get("name") or email.split("@")[0]).strip()[:100],
        "google_sub": str(sub),
    }


def is_email_registered(email, exclude_user_id=None):
    """True if `email` belongs to another account (case-insensitive)."""
    conn = get_db()
    cursor = conn.cursor()
    if exclude_user_id is None:
        cursor.execute(
            "SELECT id FROM users WHERE LOWER(email) = LOWER(?)", (email,)
        )
    else:
        cursor.execute(
            "SELECT id FROM users WHERE LOWER(email) = LOWER(?) AND id != ?",
            (email, exclude_user_id),
        )
    row = cursor.fetchone()
    conn.close()
    return row is not None


# ==========================================================
# Brute-force protection
# ==========================================================

def _prune_old_attempts(cursor):
    cutoff = (datetime.now() - timedelta(days=1)).strftime(TIME_FMT)
    cursor.execute(
        "DELETE FROM auth_attempts WHERE last_failed_at < ?", (cutoff,)
    )


def _record_activity(identifier, ip, limit):
    """Count one attempt for (identifier, ip) with a sliding window.

    Returns remaining lockout seconds if the attempt crosses the limit,
    otherwise 0.
    """
    conn = get_db()
    cursor = conn.cursor()
    _prune_old_attempts(cursor)

    now = datetime.now()
    now_str = now.strftime(TIME_FMT)
    cursor.execute(
        "SELECT * FROM auth_attempts WHERE identifier = ? AND ip = ?",
        (identifier, ip),
    )
    row = cursor.fetchone()

    count = 1
    if row:
        if row["locked_until"]:
            locked = datetime.strptime(row["locked_until"], TIME_FMT)
            if now < locked:
                conn.close()
                return max(1, int((locked - now).total_seconds()))
        last = datetime.strptime(row["last_failed_at"], TIME_FMT)
        if (now - last).total_seconds() <= LOCKOUT_WINDOW:
            count = row["fail_count"] + 1

    locked_until = None
    if count >= limit:
        locked_until = (now + timedelta(seconds=LOCKOUT_SECONDS)).strftime(TIME_FMT)

    cursor.execute(
        """
        INSERT INTO auth_attempts (identifier, ip, fail_count, locked_until, last_failed_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(identifier, ip) DO UPDATE SET
            fail_count = excluded.fail_count,
            locked_until = excluded.locked_until,
            last_failed_at = excluded.last_failed_at
        """,
        (identifier, ip, count, locked_until, now_str),
    )
    conn.commit()
    conn.close()
    return LOCKOUT_SECONDS if locked_until else 0


def record_failed_attempt(email, ip):
    """Record a failed login: account+IP first, then a shared per-IP count."""
    remaining = _record_activity(email, ip, LOCKOUT_MAX_ACCOUNT)
    if remaining:
        return remaining
    return _record_activity(f"ip:{ip}", "*", LOCKOUT_MAX_IP)


def record_ip_activity(ip):
    """Count an action (e.g. a signup attempt) against the shared per-IP limit."""
    return _record_activity(f"ip:{ip}", "*", LOCKOUT_MAX_IP)


def check_lockout(email, ip):
    """Return remaining lockout seconds for (email, ip), or 0 if allowed."""
    now = datetime.now()
    conn = get_db()
    cursor = conn.cursor()
    for identifier, ip_key in ((email, ip), (f"ip:{ip}", "*")):
        cursor.execute(
            "SELECT locked_until FROM auth_attempts WHERE identifier = ? AND ip = ?",
            (identifier, ip_key),
        )
        row = cursor.fetchone()
        if row and row["locked_until"]:
            locked = datetime.strptime(row["locked_until"], TIME_FMT)
            if now < locked:
                conn.close()
                return max(1, int((locked - now).total_seconds()))
    conn.close()
    return 0


def reset_attempts(email, ip):
    """Clear the per-account failure counter after a successful login."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM auth_attempts WHERE identifier = ? AND ip = ?", (email, ip)
    )
    conn.commit()
    conn.close()
