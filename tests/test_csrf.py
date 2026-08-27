import pytest
import secrets
from tests.conftest import make_user, login, set_csrf


@pytest.fixture
def uniq():
    return secrets.token_hex(4)


def test_post_without_token_rejected(client, uniq):
    email = f"c_{uniq}@test.local"
    make_user(email)
    client.get("/signin/")
    set_csrf(client, "tok")
    r = client.post("/signin/submit", data={"email": email, "password": "StrongPass123"})
    assert r.status_code == 400
    r = client.post("/signup/signup_button", data={
        "name": "N", "email": f"n_{uniq}@test.local", "password": "StrongPass123",
        "confirm_password": "StrongPass123", "course": "GATE",
    })
    assert r.status_code == 400


def test_post_with_wrong_token_rejected(client, uniq):
    email = f"c_{uniq}@test.local"
    make_user(email)
    client.get("/signin/")
    set_csrf(client, "tok")
    r = client.post("/signin/submit", data={"email": email, "password": "StrongPass123", "csrf_token": "wrong"})
    assert r.status_code == 400


def test_post_with_valid_token_accepted(client, uniq):
    email = f"c_{uniq}@test.local"
    make_user(email)
    client.get("/signin/")
    set_csrf(client, "tok")
    r = client.post("/signin/submit", data={"email": email, "password": "StrongPass123", "csrf_token": "tok"})
    assert r.status_code == 302
    r = client.post("/signup/signup_button", data={
        "name": "N", "email": f"n_{uniq}@test.local", "password": "StrongPass123",
        "confirm_password": "StrongPass123", "course": "GATE", "csrf_token": "tok",
    })
    assert r.status_code == 302


def test_logged_in_post_requires_token(client, uniq):
    email = f"p_{uniq}@test.local"
    uid = make_user(email)
    login(client, email, uid, "tok")
    r = client.post("/profile/update_profile", data={})
    assert r.status_code == 400
    r = client.post("/profile/update_profile", data={
        "csrf_token": "tok", "name": "T", "email": email,
        "phone": "", "college": "", "department": "", "year": "",
    })
    assert r.status_code == 302


def test_get_endpoints_unaffected(client):
    assert client.get("/").status_code == 200
    assert client.get("/signin/").status_code == 200
    assert client.get("/signup/").status_code == 200
