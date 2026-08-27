"""One-time migration: convert machine-specific PDF paths to portable filenames.

The ``uploaded_pdfs.file_path`` column used to store absolute Windows paths
such as ``D:\\INTENSHIP\\Gate-mentor\\uploads\\file.pdf``. Those paths are tied
to the computer that originally ran the app and break the project once it is
copied to another machine.

This tool rewrites every ``file_path`` value to just the portable filename
(e.g. ``file.pdf``) and makes a timestamped backup of the database first.

Usage:
    python pdf_migration.py                  # migrate the real database.db
    python pdf_migration.py <db_path>        # migrate a specific db file
    python pdf_migration.py <db_path> <upload_dir>

It is safe to run repeatedly: rows that already hold a plain filename are left
untouched and only ``file_path`` is ever modified.
"""
import ntpath
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_DB = PROJECT_ROOT / "database.db"
DEFAULT_UPLOAD_DIR = PROJECT_ROOT / "uploads"


def _portable_name(stored_path):
    """Extract the portable filename from a (possibly absolute) stored path."""
    if not stored_path or not str(stored_path).strip():
        return None
    # ntpath handles both backslash (Windows) and forward slash separators.
    name = ntpath.basename(str(stored_path).strip())
    return name or None


def migrate_pdf_paths(db_path=None, upload_dir=None):
    """Migrate file_path values in a copy of the given database.

    Always writes a timestamped backup next to ``db_path`` before modifying
    anything. Only the ``uploaded_pdfs.file_path`` column is changed; no rows
    or other tables are touched.

    Returns a dict report:
      total, updated, unchanged, missing_files, changed_ids
    """
    db_path = Path(db_path or DEFAULT_DB).resolve()
    upload_dir = Path(upload_dir or DEFAULT_UPLOAD_DIR).resolve()

    if not db_path.is_file():
        raise FileNotFoundError(f"Database not found: {db_path}")

    # 1) Backup before touching anything.
    backup = db_path.with_name(
        f"{db_path.stem}.backup_{datetime.now().strftime('%Y%m%d%H%M%S')}{db_path.suffix}"
    )
    shutil.copy2(db_path, backup)

    # 2) Read the current values.
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT id, file_path FROM uploaded_pdfs").fetchall()

    report = {
        "backup_path": str(backup),
        "total": len(rows),
        "updated": 0,
        "unchanged": 0,
        "missing_files": [],
        "existing_files": [],
        "changed_ids": [],
    }

    for row in rows:
        pdf_id = row["id"]
        old_value = row["file_path"]
        new_name = _portable_name(old_value)

        if new_name is None:
            # Empty/NULL-ish value: leave it; nothing portable to derive.
            report["unchanged"] += 1
            continue

        if new_name != old_value:
            conn.execute(
                "UPDATE uploaded_pdfs SET file_path=? WHERE id=?",
                (new_name, pdf_id),
            )
            report["updated"] += 1
            report["changed_ids"].append(pdf_id)
        else:
            report["unchanged"] += 1

        if (upload_dir / new_name).is_file():
            report["existing_files"].append(new_name)
        else:
            report["missing_files"].append(new_name)

    conn.commit()
    conn.close()

    report["changed_ids"] = sorted(report["changed_ids"])
    return report


def _print_report(report):
    print(f"Database backup written to: {report['backup_path']}")
    print(f"Total uploaded_pdfs rows:  {report['total']}")
    print(f"Rows updated:              {report['updated']}")
    print(f"Rows unchanged:            {report['unchanged']}")
    print(f"Referenced files present:  {len(report['existing_files'])}")
    print(f"Referenced files MISSING:  {len(report['missing_files'])}")
    if report["changed_ids"]:
        print("Changed IDs:", ", ".join(str(i) for i in report["changed_ids"]))
    if report["missing_files"]:
        print("Missing files (manual recovery needed):")
        for name in report["missing_files"]:
            print(f"  - {name}")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a]
    db_arg = Path(args[0]) if len(args) >= 1 else DEFAULT_DB
    upload_arg = Path(args[1]) if len(args) >= 2 else DEFAULT_UPLOAD_DIR
    report = migrate_pdf_paths(db_arg, upload_arg)
    _print_report(report)
