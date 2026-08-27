from database import get_db
from datetime import datetime

COURSES = ('GATE', 'NEET', 'GATE+NEET')

PRICE_MAP = {
    'GATE': 1000,
    'NEET': 1000,
    'GATE+NEET': 1500
}


def get_purchased_courses(user_id):
    """Return the set of course names the user has a verified PAID record for."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT course_name FROM user_courses WHERE user_id = ? AND payment_status = 'PAID'",
        (user_id,)
    )
    courses = {row['course_name'] for row in cursor.fetchall()}
    conn.close()
    return courses


def has_course_access(user_id, course):
    """True only if a verified purchase record grants access to `course`."""
    if course not in COURSES:
        return False

    purchased = get_purchased_courses(user_id)

    if course == 'GATE+NEET':
        return 'GATE+NEET' in purchased

    return course in purchased or 'GATE+NEET' in purchased


def grant_course(user_id, course_name, payment_plan, conn=None, cursor=None):
    """Record a verified purchase in user_courses (idempotent).

    Pass an open conn/cursor to commit together with the caller's transaction;
    otherwise a new connection is used.
    """
    owns_connection = conn is None
    if conn is None:
        conn = get_db()
        cursor = conn.cursor()

    purchased_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute(
        "SELECT id FROM user_courses WHERE user_id = ? AND course_name = ?",
        (user_id, course_name)
    )
    existing = cursor.fetchone()

    if existing:
        cursor.execute(
            "UPDATE user_courses SET payment_status = 'PAID', payment_plan = ?, purchased_at = ? WHERE id = ?",
            (payment_plan, purchased_at, existing['id'])
        )
    else:
        cursor.execute(
            "INSERT INTO user_courses (user_id, course_name, payment_plan, payment_status, purchased_at) "
            "VALUES (?, ?, ?, 'PAID', ?)",
            (user_id, course_name, payment_plan, purchased_at)
        )

    if owns_connection:
        conn.commit()
        conn.close()
