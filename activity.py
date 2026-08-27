from database import get_db
from datetime import datetime


def add_activity(user_id, activity_type, title, description):

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO recent_activity(
            user_id,
            activity_type,
            activity_title,
            activity_description
        )
        VALUES(?,?,?,?)
    """, (
        user_id,
        activity_type,
        title,
        description
    ))

    conn.commit()
    conn.close()


def add_study_session(user_id, course, minutes):

    conn = get_db()
    cursor = conn.cursor()

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute("""
        INSERT INTO study_sessions(
            user_id,
            course,
            session_start,
            session_end,
            duration_minutes
        )
        VALUES(?,?,?,?,?)
    """, (
        user_id,
        course,
        now,
        now,
        minutes
    ))

    conn.commit()
    conn.close()