"""Tests for portable (machine-independent) uploaded-PDF path handling.

Covers:
  1. New upload stores a portable filename in the database (no absolute path).
  2. Runtime resolution builds the real path from UPLOAD_FOLDER + filename.
  3. The same database value resolves on any machine (simulated project move).
  4. Path traversal (../../secret.pdf) is rejected.
  5. Missing PDF files are handled gracefully.
  6. The one-time migration rewrites legacy absolute paths to filenames.
"""
import io
import os
import sqlite3
from pathlib import Path

import pytest

from Main_page import app
from database import get_db
import doubt_solver
import pdf_storage
from pdf_storage import get_pdf_path, pdf_file_exists, resolve_existing_pdf
from pdf_migration import migrate_pdf_paths
from tests.conftest import make_user, login, create_pdf


def make_pdf(text):
    """Build a minimal, valid one-page PDF that pdfplumber can read."""
    content = f"BT /F1 24 Tf 72 720 Td ({text}) Tj ET".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF".encode()
    return bytes(out)


LONG_TEXT = (
    "Photosynthesis is the process by which plants convert light energy into "
    "chemical energy. During this process, plants take in carbon dioxide and "
    "water, and with the help of sunlight, they produce glucose and oxygen. "
    "This is a sample study note for the GATE engineering examination. "
    "Understanding thermodynamics is very important for mechanical engineering."
)


@pytest.fixture(autouse=True)
def _isolate_upload_folder(tmp_path):
    """Point UPLOAD_FOLDER at a temp dir for every test in this module."""
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir(exist_ok=True)
    app.config["UPLOAD_FOLDER"] = str(upload_dir)
    yield upload_dir
    app.config["UPLOAD_FOLDER"] = os.path.join(app.root_path, "uploads")


@pytest.fixture(autouse=True)
def _app_ctx():
    """Provide a Flask app context so get_pdf_path reads the app config."""
    with app.app_context():
        yield


# ---------------------------------------------------------------------------
# Test 1 - a new upload stores a portable filename, never an absolute path
# ---------------------------------------------------------------------------
def test_upload_stores_portable_filename(client, monkeypatch):
    uid = make_user("upload@example.com")
    login(client, "upload@example.com", uid, "tok1")

    # Keep the flow hermetic: no Gemini API calls.
    import question_generator
    monkeypatch.setattr(question_generator, "validate_pdf_content", lambda text, course: (True, ""))
    monkeypatch.setattr(doubt_solver, "get_embedding", lambda text, is_query=False: None)

    resp = client.post(
        "/pdf-upload/upload?course=GATE",
        data={
            "file": (io.BytesIO(make_pdf(LONG_TEXT)), "notes.pdf"),
            "csrf_token": "tok1",
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200

    conn = get_db()
    row = conn.execute(
        "SELECT id, file_path, pdf_name FROM uploaded_pdfs WHERE user_id=?",
        (uid,),
    ).fetchone()
    conn.close()
    assert row is not None

    stored = row["file_path"]
    # Portable identifier: timestamp_securedname, no drive or separators.
    assert stored.startswith("2026")
    assert stored.endswith("_notes.pdf")
    assert ":" not in stored
    assert "\\" not in stored
    assert "/" not in stored
    assert not os.path.isabs(stored)

    upload_dir = Path(app.config["UPLOAD_FOLDER"])
    assert (upload_dir / stored).is_file()

    # The indexed pages prove the upload opened the PDF through the resolver.
    conn = get_db()
    page_count = conn.execute(
        "SELECT COUNT(*) FROM uploaded_pdf_pages WHERE pdf_id=?",
        (row["id"],),
    ).fetchone()[0]
    conn.close()
    assert page_count == 1


def test_upload_keeps_original_name_for_display(client, monkeypatch):
    uid = make_user("upload2@example.com")
    login(client, "upload2@example.com", uid, "tok2")
    import question_generator
    monkeypatch.setattr(question_generator, "validate_pdf_content", lambda text, course: (True, ""))
    monkeypatch.setattr(doubt_solver, "get_embedding", lambda text, is_query=False: None)

    client.post(
        "/pdf-upload/upload?course=GATE",
        data={
            "file": (io.BytesIO(make_pdf(LONG_TEXT)), "My Study Notes.pdf"),
            "csrf_token": "tok2",
        },
        content_type="multipart/form-data",
    )
    conn = get_db()
    row = conn.execute(
        "SELECT pdf_name, file_path FROM uploaded_pdfs WHERE user_id=?",
        (uid,),
    ).fetchone()
    conn.close()
    # pdf_name stores the secure_filename() form (pre-existing app behavior).
    assert row["pdf_name"] == "My_Study_Notes.pdf"
    assert row["file_path"].endswith("_My_Study_Notes.pdf")


# ---------------------------------------------------------------------------
# Test 2 - runtime path resolution from UPLOAD_FOLDER + stored filename
# ---------------------------------------------------------------------------
def test_runtime_resolution_builds_absolute_path():
    upload_dir = Path("C:/SomeOtherLocation/Gate-mentor/uploads")
    app.config["UPLOAD_FOLDER"] = str(upload_dir)
    resolved = get_pdf_path("abc123.pdf")
    assert resolved == upload_dir / "abc123.pdf"
    assert upload_dir.resolve() in resolved.parents


# ---------------------------------------------------------------------------
# Test 3 - the same DB value resolves on any machine (simulated project move)
# ---------------------------------------------------------------------------
def test_machine_portability(tmp_path):
    machine_a = tmp_path / "D_side" / "uploads"
    machine_b = tmp_path / "C_side" / "uploads"
    machine_a.mkdir(parents=True)
    machine_b.mkdir(parents=True)

    app.config["UPLOAD_FOLDER"] = str(machine_a)
    on_a = get_pdf_path("abc123.pdf")

    app.config["UPLOAD_FOLDER"] = str(machine_b)
    on_b = get_pdf_path("abc123.pdf")

    # Same portable database value, correct on both "machines", no DB change.
    assert on_a == machine_a / "abc123.pdf"
    assert on_b == machine_b / "abc123.pdf"
    assert on_a != on_b  # real paths differ, but the stored value is identical


# ---------------------------------------------------------------------------
# Test 4 - path traversal cannot escape the upload directory
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "malicious",
    [
        "../../secret.pdf",
        "..\\..\\secret.pdf",
        "uploads/evil.pdf",
        "/etc/passwd",
        "C:\\Windows\\system32\\drivers\\etc\\hosts",
        "C:/tmp/t1.pdf",
        "..",
        "abc.pdf/..",
    ],
)
def test_path_traversal_rejected(malicious):
    with pytest.raises(ValueError):
        get_pdf_path(malicious)
    # The existence helper must never raise and must never report such a file.
    assert pdf_file_exists(malicious) is False


def test_resolved_path_never_escapes_upload_dir():
    upload_dir = Path(app.config["UPLOAD_FOLDER"]).resolve()
    for attempt in ["../../secret.pdf", "..\\..\\secret.pdf", "C:/tmp/t1.pdf"]:
        with pytest.raises(ValueError):
            get_pdf_path(attempt)
    good = get_pdf_path("abc123.pdf")
    assert upload_dir in good.parents


# ---------------------------------------------------------------------------
# Test 5 - missing PDF files are handled gracefully
# ---------------------------------------------------------------------------
def test_missing_file_helpers_are_graceful():
    app.config["UPLOAD_FOLDER"] = str(Path(app.config["UPLOAD_FOLDER"]))
    assert pdf_file_exists("missing.pdf") is False
    assert resolve_existing_pdf("missing.pdf") is None
    # The resolved path is still constructible; only existence fails.
    assert get_pdf_path("missing.pdf").name == "missing.pdf"


def test_missing_file_present_helper(tmp_path):
    present = tmp_path / "uploads" / "present.pdf"
    present.write_bytes(b"%PDF-1.4 fake")
    app.config["UPLOAD_FOLDER"] = str(tmp_path / "uploads")
    assert pdf_file_exists("present.pdf") is True
    assert resolve_existing_pdf("present.pdf") == present


def test_index_pdf_missing_file_does_not_crash():
    uid = make_user("missing@example.com")
    pid = create_pdf(uid, name="ghost.pdf")
    with app.app_context():
        result = doubt_solver.index_pdf_pages(pid, uid)
    assert result is False
    conn = get_db()
    count = conn.execute(
        "SELECT COUNT(*) FROM uploaded_pdf_pages WHERE pdf_id=?",
        (pid,),
    ).fetchone()[0]
    conn.close()
    assert count == 0


def test_index_pdf_invalid_path_does_not_crash():
    uid = make_user("invalidpath@example.com")
    pid = create_pdf(uid, name="ghost.pdf")
    conn = get_db()
    conn.execute("UPDATE uploaded_pdfs SET file_path='..\\..\\secret.pdf' WHERE id=?", (pid,))
    conn.commit()
    conn.close()
    with app.app_context():
        result = doubt_solver.index_pdf_pages(pid, uid)
    assert result is False


# ---------------------------------------------------------------------------
# Test 6 - one-time migration of legacy absolute paths
# ---------------------------------------------------------------------------
def _build_legacy_db(tmp_path):
    db = tmp_path / "legacy.db"
    uploads = tmp_path / "uploads"
    uploads.mkdir(exist_ok=True)
    (uploads / "abc.pdf").write_bytes(b"%PDF-1.4")

    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE uploaded_pdfs (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "user_id INTEGER, course TEXT, pdf_name TEXT, file_path TEXT NOT NULL, "
        "upload_time TEXT, pdf_type TEXT, total_pages INTEGER)"
    )
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("CREATE TABLE uploaded_pdf_pages (id INTEGER PRIMARY KEY, pdf_id INTEGER, page_text TEXT)")

    rows = [
        (1, "D:\\INTENSHIP\\Gate-mentor\\uploads\\abc.pdf", "ABC"),
        (2, "E:\\INTERN\\some_project\\uploads\\def.pdf", "DEF"),
        (3, "uploads/file.pdf", "FILE"),
        (4, "already_portable.pdf", "PORTABLE"),
        (5, "C:/tmp/t1.pdf", "TMP"),
    ]
    for pid, path, name in rows:
        conn.execute(
            "INSERT INTO uploaded_pdfs (id, user_id, course, pdf_name, file_path, "
            "upload_time, pdf_type, total_pages) VALUES (?, 10, 'GATE', ?, ?, 't', 'Digital', 1)",
            (pid, name, path),
        )
    conn.execute("INSERT INTO users (id, name) VALUES (10, 'keep me')")
    conn.execute("INSERT INTO uploaded_pdf_pages (id, pdf_id, page_text) VALUES (1, 1, 'keep page')")
    conn.commit()
    conn.close()
    return db, uploads


def test_migration_converts_absolute_paths_to_filenames(tmp_path):
    db, uploads = _build_legacy_db(tmp_path)
    report = migrate_pdf_paths(db_path=db, upload_dir=uploads)

    assert report["total"] == 5
    assert report["updated"] == 4  # already_portable.pdf unchanged
    assert report["unchanged"] == 1

    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    values = {r["id"]: r["file_path"] for r in conn.execute("SELECT id, file_path FROM uploaded_pdfs")}
    user = conn.execute("SELECT * FROM users WHERE id=10").fetchone()
    page = conn.execute("SELECT * FROM uploaded_pdf_pages WHERE id=1").fetchone()
    conn.close()

    assert values[1] == "abc.pdf"
    assert values[2] == "def.pdf"
    assert values[3] == "file.pdf"
    assert values[4] == "already_portable.pdf"
    assert values[5] == "t1.pdf"

    # No unrelated data touched.
    assert user["name"] == "keep me"
    assert page["page_text"] == "keep page"

    # Backup was created.
    assert Path(report["backup_path"]).is_file()

    # Files that exist are reported as present; only the C:/tmp one is missing.
    assert "abc.pdf" in report["existing_files"]
    assert "t1.pdf" in report["missing_files"]


def test_migration_is_idempotent(tmp_path):
    db, uploads = _build_legacy_db(tmp_path)
    migrate_pdf_paths(db_path=db, upload_dir=uploads)
    report = migrate_pdf_paths(db_path=db, upload_dir=uploads)
    assert report["updated"] == 0
    assert report["unchanged"] == 5
