from database import get_db
from activity import add_activity
from activity import add_study_session


def save_quiz_result(
    user_id,
    pdf_id,
    score,
    total_questions,
    percentage,
    course,
    duration_minutes=20
):
    conn = get_db()
    cursor = conn.cursor()

    try:

        # Save Quiz Result
        cursor.execute("""
            INSERT INTO quiz_results(
                user_id,
                pdf_id,
                score,
                total_questions,
                percentage,
                completed_at
            )
            VALUES(?,?,?,?,?,datetime('now'))
        """, (
            user_id,
            pdf_id,
            score,
            total_questions,
            percentage
        ))

        conn.commit()

        # Recent Activity
        add_activity(
            user_id,
            "quiz",
            "Completed AI Quiz",
            f"Score: {score}/{total_questions} ({percentage}%)"
        )

        # Study Session
        add_study_session(
            user_id,
            course,
            duration_minutes
        )

    finally:
        conn.close()