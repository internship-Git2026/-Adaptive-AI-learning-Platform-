import secrets
from database import get_db
from tests.conftest import make_user, login, create_pdf
from my_courses import get_course_progress


def insert_quiz(pdf_id, score, total):
    conn = get_db()
    conn.execute(
        "INSERT INTO quiz_results (user_id, pdf_id, score, total_questions, percentage, completed_at) "
        "VALUES ((SELECT user_id FROM uploaded_pdfs WHERE id=?), ?, ?, ?, ?, '2026-01-01 10:00:00')",
        (pdf_id, pdf_id, score, total, round(score / total * 100)),
    )
    conn.commit()
    conn.close()


def test_course_progress_computed_per_course():
    email = f"prog_{secrets.token_hex(4)}@test.local"
    uid = make_user(email)
    pid = create_pdf(uid, course="GATE", name="Data Structures.pdf")
    insert_quiz(pid, 8, 10)
    assert get_course_progress(uid, "GATE") == 80
    assert get_course_progress(uid, "NEET") == 0


def test_my_courses_shows_real_progress_not_hardcoded():
    email = f"prog_{secrets.token_hex(4)}@test.local"
    uid = make_user(email)
    pid = create_pdf(uid, course="GATE", name="Data Structures.pdf")
    insert_quiz(pid, 8, 10)
    c = __import__("Main_page").app.test_client()
    login(c, email, uid, "tok")
    html = c.get("/dashboard/my-courses/").get_data(as_text=True)
    assert ">80%<" in html
    assert "52%" not in html
    assert "55%" not in html


def test_neet_syllabus_progress_dynamic():
    email = f"prog_{secrets.token_hex(4)}@test.local"
    uid = make_user(email)
    conn = get_db()
    conn.execute("INSERT INTO user_courses (user_id, course_name, payment_plan, payment_status) VALUES (?, 'NEET', 1000, 'PAID')", (uid,))
    conn.commit()
    conn.close()
    pid = create_pdf(uid, course="NEET", name="Chemistry Organic.pdf")
    insert_quiz(pid, 6, 10)
    c = __import__("Main_page").app.test_client()
    login(c, email, uid, "tok")
    html = c.get("/dashboard/neet/").get_data(as_text=True)
    assert "60% In Progress" in html
    assert "90% Complete" not in html
