"""Tests for the simplified SM-2 spaced repetition module.

Verifies:
  - Wrong answer shrinks interval and lowers mastery
  - Correct answer grows interval and raises mastery
  - New row creation on first answer
  - get_due_revisions returns only due rows, ordered weakest-first
"""
import pytest
from datetime import datetime, timedelta

from spaced_repetition import schedule_review, get_due_revisions, _now
from database import get_db
from tests.conftest import make_user


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _get_row(user_id, subject, topic):
    conn = get_db()
    conn.row_factory = None
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM revision_schedule WHERE user_id=? AND subject=? AND topic=?",
        (user_id, subject, topic),
    )
    row = cur.fetchone()
    cols = [d[0] for d in cur.description] if cur.description else []
    conn.close()
    return dict(zip(cols, row)) if row else None


def _count_rows(user_id):
    conn = get_db()
    n = conn.execute(
        "SELECT COUNT(*) FROM revision_schedule WHERE user_id=?", (user_id,)
    ).fetchone()[0]
    conn.close()
    return n


# ------------------------------------------------------------------
# Test A — first correct answer creates a row with correct defaults
# ------------------------------------------------------------------
def test_first_correct_answer_creates_row(client):
    uid = make_user("sr_correct_a@test.local")
    schedule_review(uid, "GATE", "Data Structures", was_correct=True)

    row = _get_row(uid, "GATE", "Data Structures")
    assert row is not None
    assert row["mastery_score"] == 10   # _MASTERY_INCREMENT
    assert row["revision_count"] == 1
    assert row["wrong_answers"] == 0
    assert row["interval_days"] == 1
    assert row["last_revision"] is not None


# ------------------------------------------------------------------
# Test B — first wrong answer creates a row with correct defaults
# ------------------------------------------------------------------
def test_first_wrong_answer_creates_row(client):
    uid = make_user("sr_wrong_a@test.local")
    schedule_review(uid, "GATE", "Operating Systems", was_correct=False)

    row = _get_row(uid, "GATE", "Operating Systems")
    assert row is not None
    assert row["mastery_score"] == 0
    assert row["revision_count"] == 0
    assert row["wrong_answers"] == 1
    assert row["interval_days"] == 1
    assert row["last_revision"] is not None


# ------------------------------------------------------------------
# Test C — correct answer grows interval and raises mastery
# ------------------------------------------------------------------
def test_correct_answer_grows_interval_and_mastery(client):
    uid = make_user("sr_correct_b@test.local")

    # First correct
    schedule_review(uid, "GATE", "DBMS", was_correct=True)
    row1 = _get_row(uid, "GATE", "DBMS")
    assert row1["mastery_score"] == 10
    assert row1["interval_days"] == 1
    assert row1["revision_count"] == 1

    # Second correct — interval should grow (1 * 1.8 = 1, mastery 20)
    schedule_review(uid, "GATE", "DBMS", was_correct=True)
    row2 = _get_row(uid, "GATE", "DBMS")
    assert row2["mastery_score"] == 20
    assert row2["interval_days"] >= 1  # 1 * 1.8 → 1 (int), next will grow
    assert row2["revision_count"] == 2

    # Third correct — interval should now be > 1
    schedule_review(uid, "GATE", "DBMS", was_correct=True)
    row3 = _get_row(uid, "GATE", "DBMS")
    assert row3["mastery_score"] == 30
    assert row3["interval_days"] > 1
    assert row3["revision_count"] == 3


# ------------------------------------------------------------------
# Test D — wrong answer shrinks interval and lowers mastery
# ------------------------------------------------------------------
def test_wrong_answer_shrinks_interval_and_mastery(client):
    uid = make_user("sr_wrong_b@test.local")

    # Build up some mastery first (3 correct)
    for _ in range(3):
        schedule_review(uid, "GATE", "Networks", was_correct=True)

    row_before = _get_row(uid, "GATE", "Networks")
    assert row_before["mastery_score"] == 30
    old_interval = row_before["interval_days"]

    # Now a wrong answer
    schedule_review(uid, "GATE", "Networks", was_correct=False)
    row_after = _get_row(uid, "GATE", "Networks")
    assert row_after["mastery_score"] == 15   # 30 - 15 = 15
    assert row_after["interval_days"] == 1     # reset to 1
    assert row_after["wrong_answers"] == 1


# ------------------------------------------------------------------
# Test E — mastery floors at 0 and caps at 100
# ------------------------------------------------------------------
def test_mastery_floor_and_cap(client):
    uid = make_user("sr_floor_cap@test.local")

    # Floor: wrong on fresh topic
    schedule_review(uid, "GATE", "Compiler Design", was_correct=False)
    row = _get_row(uid, "GATE", "Compiler Design")
    assert row["mastery_score"] == 0

    # Cap: many correct answers
    for _ in range(20):
        schedule_review(uid, "NEET", "Physics", was_correct=True)
    row = _get_row(uid, "NEET", "Physics")
    assert row["mastery_score"] == 100  # capped


# ------------------------------------------------------------------
# Test F — interval never exceeds MAX_INTERVAL
# ------------------------------------------------------------------
def test_interval_cap(client):
    uid = make_user("sr_interval_cap@test.local")
    for _ in range(50):
        schedule_review(uid, "GATE", "TOC", was_correct=True)
    row = _get_row(uid, "GATE", "TOC")
    assert row["interval_days"] <= 365


# ------------------------------------------------------------------
# Test G — get_due_revisions returns only due rows, weakest first
# ------------------------------------------------------------------
def test_get_due_revisions(client):
    uid = make_user("sr_due@test.local")

    # Create two topics with different mastery
    schedule_review(uid, "GATE", "Easy Topic", was_correct=True)
    # Mastery = 10
    schedule_review(uid, "GATE", "Hard Topic", was_correct=False)
    # Mastery = 0

    # Force next_revision to today for both
    conn = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    conn.execute(
        "UPDATE revision_schedule SET next_revision = ? WHERE user_id = ?",
        (today, uid),
    )
    conn.commit()
    conn.close()

    due = get_due_revisions(uid, course="GATE")
    assert len(due) == 2
    # Weakest first (mastery 0 before mastery 10)
    assert due[0]["topic"] == "Hard Topic"
    assert due[1]["topic"] == "Easy Topic"


# ------------------------------------------------------------------
# Test H — get_due_revisions excludes future rows
# ------------------------------------------------------------------
def test_get_due_revisions_excludes_future(client):
    uid = make_user("sr_future@test.local")
    schedule_review(uid, "GATE", "Future Topic", was_correct=True)

    # Set next_revision to far future
    conn = get_db()
    future = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    conn.execute(
        "UPDATE revision_schedule SET next_revision = ? WHERE user_id = ?",
        (future, uid),
    )
    conn.commit()
    conn.close()

    due = get_due_revisions(uid)
    assert len(due) == 0


# ------------------------------------------------------------------
# Test I — get_due_revisions filters by course
# ------------------------------------------------------------------
def test_get_due_revisions_filters_by_course(client):
    uid = make_user("sr_filter@test.local")
    schedule_review(uid, "GATE", "Topic A", was_correct=True)
    schedule_review(uid, "NEET", "Topic B", was_correct=True)

    today = datetime.now().strftime("%Y-%m-%d")
    conn = get_db()
    conn.execute(
        "UPDATE revision_schedule SET next_revision = ? WHERE user_id = ?",
        (today, uid),
    )
    conn.commit()
    conn.close()

    gate_due = get_due_revisions(uid, course="GATE")
    assert len(gate_due) == 1
    assert gate_due[0]["subject"] == "GATE"

    neet_due = get_due_revisions(uid, course="NEET")
    assert len(neet_due) == 1
    assert neet_due[0]["subject"] == "NEET"


# ------------------------------------------------------------------
# Test J — each user is isolated
# ------------------------------------------------------------------
def test_users_are_isolated(client):
    uid_a = make_user("sr_iso_a@test.local")
    uid_b = make_user("sr_iso_b@test.local")

    schedule_review(uid_a, "GATE", "Shared Topic", was_correct=True)
    schedule_review(uid_b, "GATE", "Shared Topic", was_correct=False)

    row_a = _get_row(uid_a, "GATE", "Shared Topic")
    row_b = _get_row(uid_b, "GATE", "Shared Topic")

    assert row_a["mastery_score"] == 10
    assert row_b["mastery_score"] == 0
    assert _count_rows(uid_a) == 1
    assert _count_rows(uid_b) == 1
