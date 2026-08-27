import pytest
from database import get_db
from tests.conftest import create_trial


def trial_count():
    conn = get_db()
    n = conn.execute("SELECT COUNT(*) FROM guest_trials").fetchone()[0]
    conn.close()
    return n


def trial_rows(fingerprint=None):
    conn = get_db()
    if fingerprint:
        rows = conn.execute("SELECT * FROM guest_trials WHERE fingerprint=?", (fingerprint,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM guest_trials").fetchall()
    conn.close()
    return rows


def mark_used(trial_id):
    conn = get_db()
    conn.execute("UPDATE guest_trials SET trial_used=1 WHERE trial_id=?", (trial_id,))
    conn.commit()
    conn.close()


def test_trial_created_with_fingerprint_and_cookie(client):
    r = client.get("/trial/gate?fp=fp_dev_a")
    assert r.status_code == 302
    assert r.headers.get("Location", "").endswith("/trial/")
    assert "trial_id=" in r.headers.get("Set-Cookie", "")
    rows = trial_rows("fp_dev_a")
    assert len(rows) == 1
    assert rows[0]["fingerprint"] == "fp_dev_a"


def test_used_trial_blocked_after_cookie_clear(client):
    client.get("/trial/gate?fp=fp_dev_a")
    rows = trial_rows("fp_dev_a")
    mark_used(rows[0]["trial_id"])

    fresh = __import__("Main_page").app.test_client()  # cleared cookies
    r = fresh.get("/trial/gate?fp=fp_dev_a")
    assert r.status_code == 302
    assert "/trial/trial-used" in r.headers.get("Location", "")
    assert trial_count() == 1  # no new trial granted


def test_in_progress_trial_resumed_not_duplicated(client):
    client.get("/trial/gate?fp=fp_dev_b")
    fresh = __import__("Main_page").app.test_client()
    r = fresh.get("/trial/gate?fp=fp_dev_b")
    assert r.status_code == 302
    assert r.headers.get("Location", "").endswith("/trial/")
    assert "trial_id=" in r.headers.get("Set-Cookie", "")
    assert trial_count() == 1


def test_distinct_devices_get_own_trials(client):
    client.get("/trial/gate?fp=fp_dev_c")
    other = __import__("Main_page").app.test_client()
    other.get("/trial/gate?fp=fp_dev_d")
    assert trial_count() == 2
    assert len(trial_rows("fp_dev_c")) == 1
    assert len(trial_rows("fp_dev_d")) == 1


def test_existing_cookie_still_restored(client):
    client.get("/trial/gate?fp=fp_dev_e")
    rows = trial_rows("fp_dev_e")
    mark_used(rows[0]["trial_id"])
    r = client.get("/trial/gate?fp=fp_dev_e")  # same client still holds the cookie
    assert r.status_code == 302
    assert "/trial/trial-used" in r.headers.get("Location", "")


def test_ip_cap_fallback_without_fingerprint(client):
    # Simulate three already-completed trials from this IP (no device fingerprint)
    for i in range(3):
        create_trial(trial_id=f"TRIAL_IP_{i}", used=True, fingerprint=None, ip="127.0.0.1")
    r = client.get("/trial/gate")  # no fp -> per-IP cap applies
    assert r.status_code == 302
    assert "/trial/trial-used" in r.headers.get("Location", "")
    assert trial_count() == 3


def test_ip_cap_allows_first_trial_without_fingerprint(client):
    r = client.get("/trial/gate")
    assert r.status_code == 302
    assert r.headers.get("Location", "").endswith("/trial/")
    assert trial_count() == 1
