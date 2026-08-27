import pytest
import secrets
from database import get_db
from tests.conftest import make_user, login, set_csrf


@pytest.fixture
def uniq():
    return secrets.token_hex(4)


def wrong_login(client, email, count):
    for _ in range(count):
        r = client.post("/signin/submit", data={"email": email, "password": "WrongPass1", "csrf_token": "tok"})
        assert r.status_code == 401


def test_password_stored_hashed_on_signup(client, uniq):
    email = f"hash_{uniq}@test.local"
    client.get("/signup/")
    set_csrf(client, "tok")
    client.post("/signup/signup_button", data={
        "name": "N", "email": email, "password": "StrongPass123",
        "confirm_password": "StrongPass123", "course": "GATE", "csrf_token": "tok",
    })
    conn = get_db()
    row = conn.execute("SELECT password FROM users WHERE email=?", (email,)).fetchone()
    conn.close()
    assert row is not None
    assert row["password"] != "StrongPass123"
    assert not row["password"].startswith("StrongPass123")


def test_signin_wrong_password_401(client, uniq):
    email = f"w_{uniq}@test.local"
    uid = make_user(email)
    client.get("/signin/")
    set_csrf(client, "tok")
    r = client.post("/signin/submit", data={"email": email, "password": "WrongPass1", "csrf_token": "tok"})
    assert r.status_code == 401


def test_signin_correct_password_302(client, uniq):
    email = f"c_{uniq}@test.local"
    make_user(email)
    client.get("/signin/")
    set_csrf(client, "tok")
    r = client.post("/signin/submit", data={"email": email, "password": "StrongPass123", "csrf_token": "tok"})
    assert r.status_code == 302


def test_account_lockout_after_5_failures(client, uniq):
    email = f"l_{uniq}@test.local"
    make_user(email)
    client.get("/signin/")
    set_csrf(client, "tok")
    wrong_login(client, email, 5)
    r = client.post("/signin/submit", data={"email": email, "password": "StrongPass123", "csrf_token": "tok"})
    assert r.status_code == 429


def test_lockout_expires(client, uniq):
    email = f"e_{uniq}@test.local"
    make_user(email)
    client.get("/signin/")
    set_csrf(client, "tok")
    wrong_login(client, email, 5)
    conn = get_db()
    conn.execute("UPDATE auth_attempts SET locked_until = datetime('now', '-1 minute') WHERE identifier=?", (email,))
    conn.commit()
    conn.close()
    r = client.post("/signin/submit", data={"email": email, "password": "StrongPass123", "csrf_token": "tok"})
    assert r.status_code == 302


def test_other_account_unaffected_by_lockout(client, uniq):
    email_a = f"la_{uniq}@test.local"
    email_b = f"lb_{uniq}@test.local"
    make_user(email_a)
    make_user(email_b)
    client.get("/signin/")
    set_csrf(client, "tok")
    wrong_login(client, email_a, 5)
    r = client.post("/signin/submit", data={"email": email_b, "password": "StrongPass123", "csrf_token": "tok"})
    assert r.status_code == 302


def test_signup_throttle_after_20_failures(client, uniq):
    email = f"t_{uniq}@test.local"
    make_user(email)
    client.get("/signup/")
    set_csrf(client, "tok")
    for _ in range(20):
        r = client.post("/signup/signup_button", data={
            "name": "S", "email": email, "password": "StrongPass123",
            "confirm_password": "StrongPass123", "course": "GATE", "csrf_token": "tok",
        })
        assert r.status_code == 400
    r = client.post("/signup/signup_button", data={
        "name": "S", "email": f"new_{uniq}@test.local", "password": "StrongPass123",
        "confirm_password": "StrongPass123", "course": "GATE", "csrf_token": "tok",
    })
    assert r.status_code == 429


def test_email_takeover_blocked(client, uniq):
    email_a = f"a_{uniq}@test.local"
    email_b = f"b_{uniq}@test.local"
    uid_a = make_user(email_a)
    make_user(email_b)
    client.get("/signin/")
    login(client, email_a, uid_a, "tok")
    r = client.post("/profile/update_profile", data={
        "csrf_token": "tok", "name": "A", "email": email_b,
        "phone": "", "college": "", "department": "", "year": "",
    })
    assert r.status_code == 302
    conn = get_db()
    row = conn.execute("SELECT email FROM users WHERE id=?", (uid_a,)).fetchone()
    conn.close()
    assert row["email"] == email_a
