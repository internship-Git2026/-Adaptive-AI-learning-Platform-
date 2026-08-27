from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from database import get_db
import os
import logging
import datetime
from werkzeug.utils import secure_filename
from course_access import has_course_access
from pdf_storage import get_upload_folder, get_pdf_path, resolve_existing_pdf
from pdf_text_extraction import (
    extract_pdf_pages,
    clean_text,
    ExtractionError,
)

logger = logging.getLogger(__name__)

pdf_upload_bp = Blueprint('pdf_upload', __name__, url_prefix='/pdf-upload')

def get_authorized_user_and_validate(course):
    user_email = session.get("user_email")
    
    # Support Guest Trial
    trial_id = request.cookies.get("trial_id") or session.get("trial_id")
    if not user_email and trial_id:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM guest_trials WHERE trial_id = ?", (trial_id,))
        trial = cursor.fetchone()
        conn.close()
        if trial:
            if trial['course'] != course:
                return None, f"This trial is for {trial['course']}. You cannot upload files for {course}."
            if trial['pdf_credit'] <= 0:
                return None, "You have already used your free upload."
            return {"id": None, "is_guest": True, "trial_id": trial_id}, None
        else:
            return None, "Invalid trial session."

    if not user_email:
        return None, "Please sign in first."
        
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE email = ?", (user_email,))
    user = cursor.fetchone()
    conn.close()
    
    if not user or user['payment_status'] != 'PAID':
        return None, "Please purchase a course plan to access study materials."
        
    # Restrict to GATE, NEET or GATE+NEET
    if course not in ['GATE', 'NEET']:
        return None, "Invalid course parameter."
        
    if not has_course_access(user['id'], course):
        return None, f"You are not enrolled in the {course} course. Please upgrade your plan to access."
        
    return dict(user), None

@pdf_upload_bp.route('/', methods=['GET'])
def upload_page():
    user_email = session.get("user_email")
    default_course = 'GATE'
    if user_email:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT selected_course FROM users WHERE email = ?", (user_email,))
        user_row = cursor.fetchone()
        conn.close()
        if user_row and user_row['selected_course'] and user_row['selected_course'] != 'GATE+NEET':
            default_course = user_row['selected_course']
            
    course = request.args.get('course', default_course).upper()
    user, err = get_authorized_user_and_validate(course)
    if err:
        flash(err, "warning")
        return redirect(url_for('my_courses.my_courses_page'))
        
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM uploaded_pdfs WHERE user_id = ? AND course = ? ORDER BY upload_time DESC", (user['id'], course))
    uploaded_pdfs = [dict(row) for row in cursor.fetchall()]
    conn.close()
        
    return render_template('pdf_upload.html', course=course, success=False, uploaded_pdfs=uploaded_pdfs)

@pdf_upload_bp.route('/upload', methods=['POST'])
def upload_file():
    course = request.args.get('course', 'GATE').upper()
    user, err = get_authorized_user_and_validate(course)
    if err:
        flash(err, "warning")
        return redirect(url_for('my_courses.my_courses_page'))
        
    if 'file' not in request.files:
        flash("No file part selected.", "error")
        return redirect(url_for('pdf_upload.upload_page', course=course))
        
    file = request.files['file']
    if file.filename == '':
        flash("No file selected.", "error")
        return redirect(url_for('pdf_upload.upload_page', course=course))
        
    if not file.filename.lower().endswith('.pdf'):
        flash("Unsupported file format. Please upload a PDF only.", "error")
        return redirect(url_for('pdf_upload.upload_page', course=course))
        
    # Check file size (Seek method to read size without loading full file to RAM)
    file.seek(0, os.SEEK_END)
    file_length = file.tell()
    file.seek(0)
    
    if file_length > 20 * 1024 * 1024:
        flash("File too large. Maximum size allowed is 20 MB.", "error")
        return redirect(url_for('pdf_upload.upload_page', course=course))
        
    filename = secure_filename(file.filename)
    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    stored_filename = f"{timestamp}_{filename}"
    # Only the portable filename is stored in the database; the filesystem
    # path is constructed here from the authoritative upload directory.
    get_upload_folder().mkdir(parents=True, exist_ok=True)
    file_path = get_pdf_path(stored_filename)

    try:
        file.save(file_path)
    except Exception as e:
        flash(f"Failed to save file: {str(e)}", "error")
        return redirect(url_for('pdf_upload.upload_page', course=course))
        
    # Text Extraction process
    conn = None

    try:
        # Extract embedded text or run OCR (shared pipeline).
        pdf_type, pages, total_pages = extract_pdf_pages(file_path)
        extracted_text = "\n".join(text for _, text in pages)

        # Clean text
        cleaned_text = clean_text(extracted_text)
        word_count = len(cleaned_text.split())
        character_count = len(cleaned_text)

        if character_count == 0:
            raise ExtractionError(
                "No readable text could be extracted from the PDF. "
                "The document may be empty or an unreadable scan."
            )

        logger.info(
            "PDF_UPLOAD_PIPELINE: pdf='%s' method=%s pages=%d chars=%d words=%d",
            stored_filename, pdf_type, total_pages, character_count, word_count,
        )

        # AI PDF Validation
        from question_generator import validate_pdf_content
        is_valid, reject_reason = validate_pdf_content(cleaned_text, course)
        if not is_valid:
            if os.path.exists(file_path):
                os.remove(file_path)
            flash(f"AI Validation Rejected: {reject_reason}", "error")
            if user.get("is_guest"):
                return redirect(url_for('trial.dashboard'))
            return redirect(url_for('pdf_upload.upload_page', course=course))

        # Save to database
        conn = get_db()
        cursor = conn.cursor()
        upload_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        cursor.execute("""
            INSERT INTO uploaded_pdfs (
                user_id,
                trial_id,
                course,
                pdf_name,
                file_path,
                upload_time,
                pdf_type,
                total_pages,
                word_count,
                character_count,
                extracted_text,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user['id'],
            user.get('trial_id'),
            course,
            filename,
            stored_filename,
            upload_time,
            pdf_type,
            total_pages,
            word_count,
            character_count,
            cleaned_text,
            "Processed"
        ))

        conn.commit()
        pdf_id = cursor.lastrowid

        # Index pages for AI Doubt Solver
        if user.get('id'):
            try:
                from doubt_solver import index_pdf_pages
                index_pdf_pages(pdf_id, user['id'])
                from notifications import create_notification
                create_notification(
                    user_id=user['id'],
                    title="Study Material Indexed! 📚",
                    message=f"Your PDF '{filename}' has been processed and is ready for the AI Doubt Solver.",
                    category="progress"
                )
            except Exception as e:
                print("Error indexing PDF on upload:", e)

        if user.get("is_guest"):
            # Update guest_trials
            cursor.execute("""
                UPDATE guest_trials
                SET pdf_credit = 0, pdf_uploaded = 1
                WHERE trial_id = ?
            """, (user['trial_id'],))
            conn.commit()
            conn.close()
            flash("PDF uploaded and validated successfully!", "success")
            return redirect(url_for('trial.dashboard'))

        # ==========================================
        # ADD RECENT ACTIVITY
        # ==========================================
        
        cursor.execute("""
          INSERT INTO recent_activity(
          user_id,
          activity_type,
          activity_title,
          activity_description
    )
    VALUES (?,?,?,?)
""", (
    user['id'],
    "pdf",
    f"Uploaded {filename}",
    "PDF uploaded successfully"
)) 

        conn.commit()
        
        cursor.execute("SELECT * FROM uploaded_pdfs WHERE user_id = ? AND course = ? ORDER BY upload_time DESC", (user['id'], course))
        uploaded_pdfs = [dict(row) for row in cursor.fetchall()]
        conn.close()

        preview_text = cleaned_text[:1000]

        return render_template(
            "pdf_upload.html",
            course=course,
            success=True,
            has_text=True,
            pdf_id=pdf_id,
            pdf_name=filename,
            total_pages=total_pages,
            pdf_type=pdf_type,
            word_count=word_count,
            character_count=character_count,
            preview_text=preview_text,
            uploaded_pdfs=uploaded_pdfs
        )
    except Exception as e:
        if conn is not None:
            conn.close()
        if os.path.exists(file_path):
            os.remove(file_path)
        if isinstance(e, ExtractionError):
            flash(str(e), "error")
        else:
            flash(f"Extraction failed: {str(e)}", "error")
        if 'user' in locals() and user and user.get("is_guest"):
            return redirect(url_for('trial.dashboard'))
        return redirect(url_for('pdf_upload.upload_page', course=course))

@pdf_upload_bp.route('/preview/<int:pdf_id>', methods=['GET'])
def preview_file(pdf_id):
    user_email = session.get("user_email")
    if not user_email:
        flash("Please sign in first.", "info")
        return redirect(url_for('signin.signin_page'))
        
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE email = ?", (user_email,))
    user = cursor.fetchone()
    if not user:
        conn.close()
        return redirect(url_for('signin.signin_page'))
        
    cursor.execute("SELECT * FROM uploaded_pdfs WHERE id = ? AND user_id = ?", (pdf_id, user['id']))
    pdf = cursor.fetchone()
    
    if not pdf:
        conn.close()
        flash("File record not found or access denied.", "error")
        return redirect(url_for('my_courses.my_courses_page'))
        
    cursor.execute("SELECT * FROM uploaded_pdfs WHERE user_id = ? AND course = ? ORDER BY upload_time DESC", (user['id'], pdf['course']))
    uploaded_pdfs = [dict(row) for row in cursor.fetchall()]
    conn.close()

    has_text = bool(
        pdf['extracted_text'] and str(pdf['extracted_text']).strip()
    )

    return render_template(
        'pdf_upload.html',
        course=pdf['course'],
        success=True,
        has_text=has_text,
        pdf_id=pdf['id'],
        pdf_name=pdf['pdf_name'],
        total_pages=pdf['total_pages'],
        pdf_type=pdf['pdf_type'],
        word_count=pdf['word_count'],
        character_count=pdf['character_count'],
        preview_text=pdf['extracted_text'],
        uploaded_pdfs=uploaded_pdfs
    )

@pdf_upload_bp.route('/delete/<int:pdf_id>', methods=['POST'])
def delete_file(pdf_id):
    user_email = session.get("user_email")
    if not user_email:
        flash("Please sign in first.", "info")
        return redirect(url_for('signin.signin_page'))
        
    conn = get_db()
    cursor = conn.cursor()
    
    # Authenticate user and fetch file details
    cursor.execute("SELECT id FROM users WHERE email = ?", (user_email,))
    user = cursor.fetchone()
    if not user:
        conn.close()
        flash("User not found.", "error")
        return redirect(url_for('my_courses.my_courses_page'))
        
    cursor.execute("SELECT * FROM uploaded_pdfs WHERE id = ? AND user_id = ?", (pdf_id, user['id']))
    pdf = cursor.fetchone()
    
    if not pdf:
        conn.close()
        flash("File record not found or access denied.", "error")
        return redirect(url_for('my_courses.my_courses_page'))
        
    # Delete from database (scoped by owner; ownership verified above)
    cursor.execute("DELETE FROM uploaded_pdfs WHERE id = ? AND user_id = ?", (pdf_id, user['id']))
    conn.commit()
    conn.close()
    
    # Delete file from filesystem (resolved from the portable filename).
    try:
        file_path = get_pdf_path(pdf['file_path'])
        if file_path.exists():
            try:
                os.remove(file_path)
            except Exception as e:
                flash(f"Database record deleted, but failed to remove file from server: {str(e)}", "warning")
                return redirect(url_for('my_courses.my_courses_page'))
    except ValueError:
        # Stored value is not a valid portable filename; nothing to delete on disk.
        pass
            
    flash(f"Successfully deleted {pdf['pdf_name']}.", "success")
    return redirect(url_for('my_courses.my_courses_page'))

@pdf_upload_bp.route("/delete-all", methods=["POST"])
def delete_all_pdfs():

    user_email = session.get("user_email")

    if not user_email:
        flash("Please sign in first.", "error")
        return redirect(url_for("signin.signin_page"))

    conn = get_db()
    cursor = conn.cursor()

    # Get logged-in user
    cursor.execute(
        "SELECT id FROM users WHERE email=?",
        (user_email,)
    )

    user = cursor.fetchone()

    if not user:
        conn.close()
        flash("User not found.", "error")
        return redirect(url_for("signin.signin_page"))

    user_id = user["id"]

    # Get uploaded files
    course = request.args.get("course", "GATE").upper()

    cursor.execute("""
        SELECT file_path
        FROM uploaded_pdfs
        WHERE user_id=? AND course=?
    """, (user_id, course))

    pdfs = cursor.fetchall()

    # Delete physical files (resolved from each portable filename).
    for pdf in pdfs:
        try:
            path = get_pdf_path(pdf["file_path"])
        except ValueError:
            continue
        if path and path.exists():
            try:
                os.remove(path)
            except Exception:
                pass

    # Delete database records
    cursor.execute("""
        DELETE FROM uploaded_pdfs
        WHERE user_id=? AND course=?
    """, (user_id, course))

    conn.commit()
    conn.close()

    flash("All uploaded PDFs deleted successfully.", "success")

    return redirect(url_for(
        "pdf_upload.upload_page",
        course=course
    ))