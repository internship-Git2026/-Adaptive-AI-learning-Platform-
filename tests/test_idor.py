import pytest
import secrets
from database import get_db
from tests.conftest import make_user, login, create_pdf, create_question


@pytest.fixture
def uniq():
    return secrets.token_hex(4)


@pytest.fixture
def two_users(uniq):
    email_a = f"idor_a_{uniq}@test.local"
    email_b = f"idor_b_{uniq}@test.local"
    uid_a = make_user(email_a)
    uid_b = make_user(email_b)
    pdf_a = create_pdf(uid_a, name="a_notes.pdf", text="Top secret A-only notes.")
    pdf_b = create_pdf(uid_b, name="b_notes.pdf", text="B public notes.")
    qa = create_question(pdf_a)
    return email_a, uid_a, email_b, uid_b, pdf_a, pdf_b, qa


def make_clients(two_users):
    email_a, uid_a, email_b, uid_b, *_ = two_users
    cA = __import__("Main_page").app.test_client()
    cB = __import__("Main_page").app.test_client()
    login(cA, email_a, uid_a, "tokA")
    login(cB, email_b, uid_b, "tokB")
    return cA, cB


def test_settings_other_pdf_denied(two_users):
    email_a, uid_a, email_b, uid_b, pdf_a, pdf_b, qa = two_users
    cB = __import__("Main_page").app.test_client()
    login(cB, email_b, uid_b, "tokB")
    r = cB.get(f"/ai-quiz/settings/{pdf_a}")
    assert r.status_code == 302
    assert "/ai-quiz/settings" not in r.headers.get("Location", "")


def test_generate_other_pdf_denied_and_no_ai_call(two_users, no_gemini):
    email_a, uid_a, email_b, uid_b, pdf_a, pdf_b, qa = two_users
    cB = __import__("Main_page").app.test_client()
    login(cB, email_b, uid_b, "tokB")
    r = cB.post(f"/ai-quiz/generate/{pdf_a}", data={
        "csrf_token": "tokB", "question_count": 10, "difficulty": "Medium", "duration": 20,
    })
    assert r.status_code == 302
    assert no_gemini == []


def test_start_other_pdf_denied(two_users):
    email_a, uid_a, email_b, uid_b, pdf_a, pdf_b, qa = two_users
    cB = __import__("Main_page").app.test_client()
    login(cB, email_b, uid_b, "tokB")
    r = cB.get(f"/ai-quiz/start/{pdf_a}")
    assert r.status_code == 302
    assert "/ai-quiz/start" not in r.headers.get("Location", "")


def test_question_other_pdf_denied(two_users):
    email_a, uid_a, email_b, uid_b, pdf_a, pdf_b, qa = two_users
    cB = __import__("Main_page").app.test_client()
    login(cB, email_b, uid_b, "tokB")
    assert cB.get(f"/ai-quiz/question/{qa}").status_code == 302


def test_submit_answer_other_pdf_denied(two_users):
    email_a, uid_a, email_b, uid_b, pdf_a, pdf_b, qa = two_users
    cB = __import__("Main_page").app.test_client()
    login(cB, email_b, uid_b, "tokB")
    r = cB.post(f"/ai-quiz/submit/{qa}", data={"csrf_token": "tokB", "answer": 0})
    assert r.status_code == 302


def test_result_other_pdf_denied(two_users):
    email_a, uid_a, email_b, uid_b, pdf_a, pdf_b, qa = two_users
    cB = __import__("Main_page").app.test_client()
    login(cB, email_b, uid_b, "tokB")
    assert cB.get(f"/ai-quiz/result/{pdf_a}").status_code == 302


def test_preview_other_pdf_denied(two_users):
    email_a, uid_a, email_b, uid_b, pdf_a, pdf_b, qa = two_users
    cB = __import__("Main_page").app.test_client()
    login(cB, email_b, uid_b, "tokB")
    r = cB.get(f"/pdf-upload/preview/{pdf_a}")
    assert r.status_code == 302
    assert "/pdf-upload/preview" not in r.headers.get("Location", "")


def test_delete_other_pdf_denied(two_users):
    email_a, uid_a, email_b, uid_b, pdf_a, pdf_b, qa = two_users
    cB = __import__("Main_page").app.test_client()
    login(cB, email_b, uid_b, "tokB")
    cB.post(f"/pdf-upload/delete/{pdf_a}", data={"csrf_token": "tokB"})
    conn = get_db()
    still = conn.execute("SELECT 1 FROM uploaded_pdfs WHERE id=?", (pdf_a,)).fetchone()
    conn.close()
    assert still is not None


def test_doubt_history_other_user_denied(two_users):
    email_a, uid_a, email_b, uid_b, pdf_a, pdf_b, qa = two_users
    conn = get_db()
    conn.execute("INSERT INTO ai_doubt_history (user_id, question, answer) VALUES (?, 'A q', 'A ans')", (uid_a,))
    doubt_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    conn.close()
    cB = __import__("Main_page").app.test_client()
    login(cB, email_b, uid_b, "tokB")
    cB.post(f"/dashboard/doubt-solver/delete/{doubt_id}", data={"csrf_token": "tokB"})
    conn = get_db()
    still = conn.execute("SELECT 1 FROM ai_doubt_history WHERE id=?", (doubt_id,)).fetchone()
    conn.close()
    assert still is not None


def test_trial_cannot_reach_paid_pdf(two_users):
    email_a, uid_a, email_b, uid_b, pdf_a, pdf_b, qa = two_users
    from tests.conftest import create_trial
    create_trial(trial_id="TRIAL_T", fingerprint=None, ip="127.0.0.1")
    cT = __import__("Main_page").app.test_client()
    cT.set_cookie("trial_id", "TRIAL_T")
    r = cT.get(f"/trial/quiz/start/{pdf_a}")
    assert r.status_code == 302
    assert "trial/quiz" not in r.headers.get("Location", "")
    r = cT.get(f"/trial/result/{pdf_a}")
    assert r.status_code == 302


def test_anonymous_redirected_to_signin(two_users):
    email_a, uid_a, email_b, uid_b, pdf_a, pdf_b, qa = two_users
    c = __import__("Main_page").app.test_client()
    r = c.get(f"/ai-quiz/settings/{pdf_a}")
    assert r.status_code == 302
    assert "/signin" in r.headers.get("Location", "")


def test_invalid_ids_denied(two_users):
    email_a, uid_a, email_b, uid_b, pdf_a, pdf_b, qa = two_users
    cB = __import__("Main_page").app.test_client()
    login(cB, email_b, uid_b, "tokB")
    assert cB.get("/ai-quiz/settings/999999").status_code == 302
    assert cB.get("/ai-quiz/question/999999").status_code == 302


def test_no_existence_oracle(two_users):
    email_a, uid_a, email_b, uid_b, pdf_a, pdf_b, qa = two_users
    cB = __import__("Main_page").app.test_client()
    login(cB, email_b, uid_b, "tokB")
    missing = cB.get("/ai-quiz/settings/999999").status_code
    other_user = cB.get(f"/ai-quiz/settings/{pdf_a}").status_code
    assert missing == other_user


def test_legitimate_flow(two_users, no_gemini):
    email_a, uid_a, email_b, uid_b, pdf_a, pdf_b, qa = two_users
    cA = __import__("Main_page").app.test_client()
    login(cA, email_a, uid_a, "tokA")
    assert cA.get(f"/ai-quiz/settings/{pdf_a}").status_code == 200
    r = cA.post(f"/ai-quiz/generate/{pdf_a}", data={
        "csrf_token": "tokA", "question_count": 10, "difficulty": "Medium", "duration": 20,
    })
    assert r.status_code == 302
    assert no_gemini and no_gemini[0][0] == pdf_a
    assert cA.get(f"/ai-quiz/start/{pdf_a}").status_code == 200
    with cA.session_transaction() as sess:
        sess["quiz_end_time"] = "2099-01-01 00:00:00"
    assert cA.get(f"/ai-quiz/question/{qa}").status_code == 200
    assert cA.post(f"/ai-quiz/submit/{qa}", data={"csrf_token": "tokA", "answer": 0}).status_code == 200
    assert cA.get(f"/ai-quiz/result/{pdf_a}").status_code == 200
    assert cA.get(f"/pdf-upload/preview/{pdf_a}").status_code == 200


def test_own_resources_work(two_users):
    email_a, uid_a, email_b, uid_b, pdf_a, pdf_b, qa = two_users
    cB = __import__("Main_page").app.test_client()
    login(cB, email_b, uid_b, "tokB")
    assert cB.get(f"/ai-quiz/settings/{pdf_b}").status_code == 200
    assert cB.get(f"/pdf-upload/preview/{pdf_b}").status_code == 200
