"""Central authority for uploaded-PDF storage paths.

The database stores only a portable filename (e.g. ``20260814093000_abc.pdf``),
never a machine-specific absolute path. Every feature that needs the actual PDF
resolves the stored filename through this module so the project can be moved
between computers without touching the database.
"""
import os
from pathlib import Path

from flask import current_app


def get_upload_folder():
    """Return the authoritative upload directory as a :class:`pathlib.Path`.

    Reads ``UPLOAD_FOLDER`` from the Flask app config. Falls back to
    ``<project_root>/uploads`` for scripts that run outside a request context
    (e.g. the path migration tool) or if the app never configured it.
    """
    try:
        configured = current_app.config.get("UPLOAD_FOLDER")
    except RuntimeError:
        # No Flask app context (e.g. standalone migration script).
        configured = None
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parent / "uploads"


def get_pdf_path(stored_filename):
    """Resolve a stored portable filename to an absolute path under UPLOAD_FOLDER.

    The stored value must be a plain filename with no directory components,
    drive letters, or ``..`` segments. Anything else raises ``ValueError`` so a
    path traversal attempt (``../../secret.pdf``) can never escape the upload
    directory.

    The returned path is resolved and verified to live inside the upload
    directory. The file itself is not required to exist.
    """
    if not stored_filename or not str(stored_filename).strip():
        raise ValueError("PDF filename is empty.")

    name = Path(stored_filename)
    # A plain filename has no separators, no drive prefix and no parent.
    # Comparing against str(name) catches "sub/abc.pdf", "..\\..\\secret.pdf",
    # "C:\\x\\abc.pdf", "/etc/passwd", etc.
    if name.name != str(name):
        raise ValueError("Invalid PDF filename (must be a plain filename).")
    if name.name in (".", "..") or name.parts[-1:] in (("..",),):
        raise ValueError("Invalid PDF filename.")

    upload_dir = get_upload_folder().resolve()
    pdf_path = (upload_dir / name.name).resolve()
    if upload_dir != pdf_path.parent and upload_dir not in pdf_path.parents:
        raise ValueError("Invalid PDF filename (resolves outside the upload directory).")
    return pdf_path


def pdf_file_exists(stored_filename):
    """Return True if the stored filename resolves to an existing PDF file.

    Never raises: invalid filenames and missing files both return False so
    callers can handle them gracefully.
    """
    try:
        path = get_pdf_path(stored_filename)
    except ValueError:
        return False
    return path.is_file()


def resolve_existing_pdf(stored_filename):
    """Return the resolved path when the PDF exists, otherwise None.

    Convenience wrapper for callers that want graceful missing-file handling
    (e.g. index/delete flows). Logs a debug hint; never raises.
    """
    try:
        path = get_pdf_path(stored_filename)
    except ValueError:
        return None
    if not path.is_file():
        return None
    return path
