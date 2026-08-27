"""Simplified SM-2 spaced repetition engine.

Reads and writes the ``revision_schedule`` table created in database.py.
Each row is keyed by (user_id, subject, topic) — one slot per topic per user.

Public API:
    schedule_review(user_id, subject, topic, was_correct, pdf_id=None)
    get_due_revisions(user_id, course=None)
"""

import logging
from datetime import datetime, timedelta

from database import get_db

logger = logging.getLogger(__name__)

# SM-2 constants
_MIN_INTERVAL = 1        # minimum interval in days
_MAX_INTERVAL = 365      # cap so nobody gets a 10-year gap
_INTERVAL_MULTIPLIER_CORRECT = 1.8  # correct answer multiplies interval
_MASTERY_INCREMENT = 10             # points gained per correct answer
_MASTERY_DECREMENT = 15             # points lost per wrong answer
_MASTERY_FLOOR = 0
_MASTERY_CAP = 100

_TIME_FMT = "%Y-%m-%d %H:%M:%S"
_DATE_FMT = "%Y-%m-%d"


def _now():
    """Return the current datetime (stub-friendly for tests)."""
    return datetime.now()


def schedule_review(user_id, subject, topic, was_correct, pdf_id=None):
    """Upsert a revision row for (user_id, subject, topic).

    On wrong answer:
        - increment wrong_answers
        - reset interval_days to 1
        - set next_revision to tomorrow
        - decrease mastery_score (floor at 0)

    On correct answer:
        - increment revision_count
        - increase interval_days (×1.8, capped)
        - increase mastery_score (cap at 100)
        - set next_revision to today + interval_days

    Always updates last_revision to now.
    """
    conn = get_db()
    cursor = conn.cursor()
    now = _now()
    now_str = now.strftime(_TIME_FMT)

    # Look for existing row
    cursor.execute(
        "SELECT * FROM revision_schedule WHERE user_id = ? AND subject = ? AND topic = ?",
        (user_id, subject, topic),
    )
    row = cursor.fetchone()

    if row:
        # Update existing
        mastery = row["mastery_score"]
        interval = row["interval_days"]
        wrong = row["wrong_answers"]
        rev_count = row["revision_count"]

        if was_correct:
            mastery = min(mastery + _MASTERY_INCREMENT, _MASTERY_CAP)
            interval = max(1, round(interval * _INTERVAL_MULTIPLIER_CORRECT))
            interval = min(interval, _MAX_INTERVAL)
            rev_count += 1
            next_rev = (now + timedelta(days=interval)).strftime(_DATE_FMT)
        else:
            mastery = max(mastery - _MASTERY_DECREMENT, _MASTERY_FLOOR)
            interval = _MIN_INTERVAL
            wrong += 1
            next_rev = (now + timedelta(days=1)).strftime(_DATE_FMT)

        cursor.execute(
            """UPDATE revision_schedule
               SET mastery_score = ?, interval_days = ?, wrong_answers = ?,
                   revision_count = ?, next_revision = ?, last_revision = ?,
                   pdf_id = COALESCE(?, pdf_id)
               WHERE id = ?""",
            (mastery, interval, wrong, rev_count, next_rev, now_str,
             pdf_id, row["id"]),
        )
    else:
        # Insert new row
        if was_correct:
            mastery = _MASTERY_INCREMENT
            interval = _MIN_INTERVAL
            rev_count = 1
            wrong = 0
            next_rev = (now + timedelta(days=interval)).strftime(_DATE_FMT)
        else:
            mastery = _MASTERY_FLOOR
            interval = _MIN_INTERVAL
            rev_count = 0
            wrong = 1
            next_rev = (now + timedelta(days=1)).strftime(_DATE_FMT)

        cursor.execute(
            """INSERT INTO revision_schedule
               (user_id, pdf_id, subject, topic, mastery_score, wrong_answers,
                revision_count, interval_days, next_revision, last_revision)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, pdf_id, subject, topic, mastery, wrong,
             rev_count, interval, next_rev, now_str),
        )

    conn.commit()
    conn.close()


def get_due_revisions(user_id, course=None):
    """Return rows from revision_schedule where next_revision <= today.

    Ordered by mastery_score ascending (weakest topics first).
    When *course* is provided, filters by subject = course.

    Returns a list of dicts.
    """
    conn = get_db()
    conn.row_factory = None  # we want plain rows
    cursor = conn.cursor()

    today = _now().strftime(_DATE_FMT)

    if course:
        cursor.execute(
            """SELECT * FROM revision_schedule
               WHERE user_id = ? AND subject = ? AND next_revision <= ?
               ORDER BY mastery_score ASC, next_revision ASC""",
            (user_id, course, today),
        )
    else:
        cursor.execute(
            """SELECT * FROM revision_schedule
               WHERE user_id = ? AND next_revision <= ?
               ORDER BY mastery_score ASC, next_revision ASC""",
            (user_id, today),
        )

    rows = cursor.fetchall()
    conn.close()

    # Convert to dicts
    if not rows:
        return []

    columns = [desc[0] for desc in cursor.description] if cursor.description else []
    return [dict(zip(columns, row)) for row in rows]
