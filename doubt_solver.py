import json
import sqlite3
import logging
import os
import requests
from datetime import datetime, date
from flask import Blueprint, render_template, redirect, url_for, session, flash, request, jsonify
from database import get_db, DB_PATH
from notifications import create_notification
from activity import add_activity
from llm import generate
from pdf_storage import get_pdf_path
from pdf_text_extraction import extract_pdf_pages
from course_access import has_course_access, get_purchased_courses

logger = logging.getLogger(__name__)

doubt_solver_bp = Blueprint('doubt_solver', __name__, url_prefix='/dashboard/doubt-solver')

def _matches_course(pdf_name, subject, course):
    """Check if a doubt history item belongs to the given course.
    
    The `subject` field in ai_doubt_history stores the course name
    (e.g. 'GATE' or 'NEET') derived from the PDF's course column.
    We use that directly for reliable filtering.
    """
    # If subject field contains the course name, use it directly
    if subject:
        subject_upper = subject.strip().upper()
        if subject_upper == course:
            return True
        if subject_upper in ('GATE', 'NEET'):
            # subject is a known course but different from requested
            return False
    # Fallback for legacy entries without course info — show in both
    return True

# Helper to clean text
def clean_extracted_text(text):
    if not text:
        return ""
    import re
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    cleaned_lines = []
    for line in text.split('\n'):
        line_str = line.strip()
        line_str = re.sub(r'[ \t]+', ' ', line_str)
        if re.match(r'^(page)?\s*\d+\s*(of\s*\d+)?$', line_str, re.I):
            continue
        cleaned_lines.append(line_str)
    cleaned_text = '\n'.join(cleaned_lines)
    cleaned_text = re.sub(r'\n\s*\n', '\n\n', cleaned_text)
    return cleaned_text.strip()

# Helper to compute keyword-overlap score (fallback scoring for ranking pages)
def rank_pages(pages, query, query_embedding=None):
    """Rank PDF page rows by keyword overlap with the query.

    Accepts (and ignores) an optional embedding for backwards compatibility.
    Returns a list of (score, page) tuples sorted descending.
    """
    scored = [(keyword_score(query, page['page_text'] or ''), page) for page in pages]
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored


def keyword_score(query: str, text: str) -> float:
    """Simple keyword overlap score as fallback when embeddings fail."""
    import re
    query_words = set(re.findall(r'[a-z]+', query.lower()))
    stop = {'the','a','an','is','in','of','and','to','for','what','how','why','when','are','was','were','can','does','do','this','that','with','from','on','as','by','be','it','its','at','or','not'}
    query_words -= stop
    if not query_words:
        return 0.0
    text_lower = text.lower()
    hits = sum(1 for w in query_words if w in text_lower)
    return hits / len(query_words)

# Function to index pages of a PDF
def index_pdf_pages(pdf_id, user_id=None):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Scope the lookup by owner when the caller knows it, so this helper can
    # never be used to read/process another user's PDF.
    if user_id is not None:
        cursor.execute("SELECT * FROM uploaded_pdfs WHERE id=? AND user_id=?", (pdf_id, user_id))
    else:
        cursor.execute("SELECT * FROM uploaded_pdfs WHERE id=?", (pdf_id,))
    pdf = cursor.fetchone()
    if not pdf:
        conn.close()
        return False
        
    user_id = pdf['user_id']

    # Resolve the stored portable filename to the real filesystem path. A
    # missing or invalid value must not crash indexing: report it and let the
    # caller fall back gracefully.
    try:
        file_path = get_pdf_path(pdf['file_path'])
    except ValueError as exc:
        logger.warning("Skipping PDF %s: %s", pdf_id, exc)
        conn.close()
        return False
    if not file_path.is_file():
        logger.warning(
            "PDF %s (%s) is referenced in the database but the file is missing "
            "from the upload directory; skipping indexing.",
            pdf_id, pdf['file_path'],
        )
        conn.close()
        return False
    
    # Check if already indexed
    cursor.execute("SELECT COUNT(*) FROM uploaded_pdf_pages WHERE pdf_id=?", (pdf_id,))
    count = cursor.fetchone()[0]
    if count > 0:
        conn.close()
        return True
        
    pages_text = []
    try:
        # Shared extraction: embedded text, or OCR that reads each page's
        # embedded raster image directly (see pdf_text_extraction).
        _, pages_text, _ = extract_pdf_pages(file_path)
    except Exception as e:
        print(f"Error reading PDF {pdf_id} pages for indexing:", e)
        conn.close()
        return False

    for page_num, raw_txt in pages_text:
        cleaned = clean_extracted_text(raw_txt)
        if len(cleaned) < 10:
            continue
        cursor.execute("""
            INSERT INTO uploaded_pdf_pages (pdf_id, user_id, page_number, page_text)
            VALUES (?, ?, ?, ?)
        """, (pdf_id, user_id, page_num, cleaned))

    conn.commit()
    conn.close()
    return True

# YouTube search for related educational videos
def search_youtube_videos(query, course='GATE', max_results=3):
    """Search YouTube Data API for educational videos related to the doubt.
    
    Always prepends course name and educational keywords to ensure
    results are tutorial/lecture content relevant to GATE or NEET.
    """
    api_key = os.getenv("YOUTUBE_API_KEY", "")
    if not api_key:
        logger.warning("DOUBT_SOLVER: YOUTUBE_API_KEY not set")
        return []

    # Build an education-focused search query
    course_label = 'GATE exam' if course == 'GATE' else 'NEET exam'
    educational_query = f"{query} {course_label} tutorial lecture study"

    params = {
        "key": api_key,
        "q": educational_query,
        "part": "snippet",
        "type": "video",
        "maxResults": max_results,
        "relevanceLanguage": "en",
        "videoDuration": "medium",
        "safeSearch": "strict",
        "order": "relevance",
    }

    try:
        resp = requests.get("https://www.googleapis.com/youtube/v3/search", params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("DOUBT_SOLVER: YouTube API request failed: %s", exc)
        return []

    results = []
    for item in data.get("items", []):
        snippet = item.get("snippet", {})
        video_id = item.get("id", {}).get("videoId", "")
        if not video_id:
            continue
        title = snippet.get("title", "Untitled")
        channel = snippet.get("channelTitle", "")
        thumbnail = snippet.get("thumbnails", {}).get("medium", {}).get("url", "")
        url = f"https://www.youtube.com/watch?v={video_id}"
        results.append({
            "title": title,
            "url": url,
            "channel": channel or "YouTube",
            "thumbnail": thumbnail,
        })

    return results


# Ensure all user's PDFs are indexed
def ensure_user_pdfs_indexed(user_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT id, pdf_type FROM uploaded_pdfs WHERE user_id=?", (user_id,))
    pdfs = cursor.fetchall()
    
    for pdf in pdfs:
        pdf_id = pdf['id']
        cursor.execute("SELECT COUNT(*) FROM uploaded_pdf_pages WHERE pdf_id=?", (pdf_id,))
        count = cursor.fetchone()[0]
        
        if count == 0:
            # Not indexed yet - index on the fly
            logger.info("Indexing PDF %s on the fly for user %s...", pdf_id, user_id)
            conn.close()
            index_pdf_pages(pdf_id, user_id)
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            continue

        # Rows whose page_text is unusable cannot be searched; rebuild those
        # pages from the PDF.
        cursor.execute(
            "SELECT COUNT(*) FROM uploaded_pdf_pages "
            "WHERE pdf_id=? AND (page_text IS NULL OR page_text = '')",
            (pdf_id,),
        )
        if cursor.fetchone()[0] > 0:
            logger.warning("Rebuilding PDF %s pages (missing page text)...", pdf_id)
            cursor.execute("DELETE FROM uploaded_pdf_pages WHERE pdf_id=?", (pdf_id,))
            conn.commit()
            conn.close()
            index_pdf_pages(pdf_id, user_id)
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            continue

    conn.commit()
    conn.close()

# Main AI Doubt Solver Dashboard Route
@doubt_solver_bp.route('/', methods=['GET', 'POST'])
def solver_page():
    user_email = session.get("user_email")
    if not user_email:
        flash("Please sign in first.", "info")
        return redirect(url_for('signin.signin_page'))

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE email=?", (user_email,))
    user = cursor.fetchone()

    if not user:
        conn.close()
        session.clear()
        return redirect(url_for('signin.signin_page'))

    # Original guard rail: require payment
    if user['payment_status'] != 'PAID':
        conn.close()
        flash("Please purchase a course plan to access the AI Doubt Solver.", "info")
        return redirect(url_for('plans.plans_page'))

    user_id = user['id']

    # Determine which courses the user has access to
    purchased_courses = get_purchased_courses(user_id)
    has_gate = has_course_access(user_id, 'GATE')
    has_neet = has_course_access(user_id, 'NEET')
    both_courses = has_gate and has_neet

    # Determine active course from query param or default
    course_param = request.args.get('course', '').strip().upper()
    if both_courses:
        # User has both: use query param or default to GATE
        active_course = course_param if course_param in ('GATE', 'NEET') else 'GATE'
    elif has_neet:
        active_course = 'NEET'
    elif has_gate:
        active_course = 'GATE'
    else:
        # Fallback: shouldn't happen due to payment guard rail above
        active_course = 'GATE'

    # Auto-index user PDFs
    ensure_user_pdfs_indexed(user_id)
    
    active_doubt = None
    if request.method == 'POST':
        # Override active_course from hidden form field if present
        form_course = request.form.get('active_course', '').strip().upper()
        if form_course in ('GATE', 'NEET'):
            active_course = form_course

        question = request.form.get("question", "").strip()
        if not question:
            conn.close()
            flash("Please enter a question.", "warning")
            return redirect(url_for('doubt_solver.solver_page', course=active_course))

        # Check if user has uploaded PDFs for this specific course
        cursor.execute("SELECT COUNT(*) FROM uploaded_pdfs WHERE user_id=? AND course=?", (user_id, active_course))
        pdf_count = cursor.fetchone()[0]
        if pdf_count == 0:
            conn.close()
            flash(f"You haven't uploaded any {active_course} study materials yet! Please upload a PDF first.", "warning")
            return redirect(url_for('doubt_solver.solver_page', course=active_course))

        # Perform Semantic Search — only from PDFs matching the active course
        cursor.execute("""
            SELECT p.id, p.pdf_id, p.page_number, p.page_text, p.embedding, u.pdf_name, u.course
            FROM uploaded_pdf_pages p
            JOIN uploaded_pdfs u ON p.pdf_id = u.id
            WHERE p.user_id=? AND u.course=?
        """, (user_id, active_course))
        pages = cursor.fetchall()

        if not pages:
            conn.close()
            flash("No study notes found in the system database. Try uploading or re-uploading your PDF.", "warning")
            return redirect(url_for('doubt_solver.solver_page'))

        # Rank pages by keyword relevance (keyword search only).
        ranked_pages = rank_pages(pages, question)
        
        # Take top 3 pages
        top_matches = ranked_pages[:3]
        best_score = top_matches[0][0] if top_matches else 0.0
        
        # Build Context
        context_parts = []
        referenced_pdfs = []
        for score, page in top_matches:
            context_parts.append(f"Source: {page['pdf_name']} (Page {page['page_number']})\n{page['page_text']}")
            referenced_pdfs.append(f"{page['pdf_name']} (Page {page['page_number']})")
            
        context_text = "\n\n---\n\n".join(context_parts)
        
        # Construct Prompt for Groq
        prompt = f"""
You are an expert AI Doubt Solver helping a student preparing for GATE/NEET exams.
Answer the student's question thoroughly using the provided context from their uploaded notes.
The context below is extracted directly from their uploaded study material.

Rules:
1. Use the provided Context as your PRIMARY source to answer.
2. If the Context contains relevant information, always answer using it.
3. Only if the Context is COMPLETELY EMPTY or ENTIRELY UNRELATED (different subject, no overlap), respond with JSON: {{"not_found": true, "answer": "I could not find this information in your uploaded notes."}}
4. Keep the explanation beginner-friendly, simple, yet academically rigorous.
5. Do NOT fabricate facts. Stay close to what the context says.

Format your response as a JSON object with these fields:
1. "short_definition": A brief 1-2 sentence definition.
2. "detailed_explanation": A detailed explanation.
3. "simple_example": A simple illustrative example.
4. "real_world_analogy": A real-world analogy.
5. "exam_points": A list of key exam-important points.
6. "common_mistakes": A list of common student mistakes.
7. "revision_summary": A quick summary for revision.
8. "difficulty": "Easy", "Medium", or "Hard".
9. "chapter": Chapter/section name from context, or "General".
10. "topic": Specific topic name, or "General".
11. "related_questions": A list of exactly 3 follow-up questions.
12. "suggested_revision_topics": A list of 2-3 related revision topics.

Context (from uploaded notes):
{context_text}

Student Question:
{question}

Return ONLY the raw JSON string. Do not wrap in ```json or ```.
"""
        ans_json = None
        pdf_ref = top_matches[0][1]['pdf_name'] if top_matches else "Unknown PDF"
        page_ref = str(top_matches[0][1]['page_number']) if top_matches else "1"
        chap_ref = "General"
        topic_ref = "General"
        
        try:
            output = generate(prompt)
            
            # Clean markdown if present
            if output.startswith("```json"):
                output = output.replace("```json", "")
            if output.startswith("```"):
                output = output.replace("```", "")
            if output.endswith("```"):
                output = output.replace("```", "")
            output = output.strip()
            
            ans_json = json.loads(output)
            
            if ans_json.get("not_found") or "I could not find this information" in ans_json.get("answer", ""):
                ans_text = "I could not find this information in your uploaded notes."
                pdf_ref = "N/A"
                page_ref = "N/A"
                chap_ref = "N/A"
                topic_ref = "N/A"
            else:
                ans_text = json.dumps(ans_json)
                chap_ref = ans_json.get("chapter", "General")
                topic_ref = ans_json.get("topic", "General")
        except Exception as e:
            print("Groq solver error:", e)
            ans_text = "I could not find this information in your uploaded notes."
            pdf_ref = "N/A"
            page_ref = "N/A"
            chap_ref = "N/A"
            topic_ref = "N/A"

        # Determine subject course category from PDF — always use the active course
        subj = active_course

        # Save to History
        cursor.execute("""
            INSERT INTO ai_doubt_history (user_id, question, answer, pdf_name, page_number, chapter, topic, subject)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, question, ans_text, pdf_ref, page_ref, chap_ref, topic_ref, subj))
        conn.commit()
        doubt_id = cursor.lastrowid
        
        # Trigger Notifications
        # 1. Check if first AI question
        cursor.execute("SELECT COUNT(*) FROM ai_doubt_history WHERE user_id=?", (user_id,))
        total_questions = cursor.fetchone()[0]
        if total_questions == 1:
            create_notification(
                user_id=user_id,
                title="First AI Doubt Solved! 🎓",
                message="Congratulations on asking your first doubt. The AI Doubt Solver is here to guide you.",
                category="achievement"
            )
            
        # 2. Check Daily Question Goal (e.g. 5 questions)
        cursor.execute("SELECT COUNT(*) FROM ai_doubt_history WHERE user_id=? AND DATE(created_at) = DATE('now')", (user_id,))
        daily_count = cursor.fetchone()[0]
        if daily_count == 5:
            create_notification(
                user_id=user_id,
                title="Daily Doubt Goal Achieved! 🏆",
                message="Awesome! You have asked 5 doubts today and kept your learning momentum going.",
                category="achievement"
            )

        # Log Activity
        cursor.execute("""
            INSERT INTO recent_activity (user_id, activity_type, activity_title, activity_description)
            VALUES (?, 'quiz', ?, ?)
        """, (user_id, "Asked AI Doubt Solver", f"Asked: '{question[:40]}...'. Referenced {pdf_ref}."))
        conn.commit()
        
        conn.close()
        # Fetch related YouTube videos (education-focused)
        youtube_videos = []
        try:
            youtube_videos = search_youtube_videos(question, course=active_course)
        except Exception as exc:
            logger.warning("DOUBT_SOLVER: YouTube search failed: %s", exc)

        return redirect(url_for('doubt_solver.solver_page', active_doubt_id=doubt_id, course=active_course))

    # Handle GET request
    active_doubt_id = request.args.get("active_doubt_id")
    if active_doubt_id:
        cursor.execute("SELECT * FROM ai_doubt_history WHERE id=? AND user_id=?", (active_doubt_id, user_id))
        active_row = cursor.fetchone()
        if active_row:
            active_doubt = dict(active_row)
            # Parse JSON answer if it's JSON
            if active_doubt['answer'].startswith('{'):
                try:
                    active_doubt['parsed_answer'] = json.loads(active_doubt['answer'])
                except Exception:
                    active_doubt['parsed_answer'] = None
            else:
                active_doubt['parsed_answer'] = None

    # Fetch related YouTube videos for active doubt (education-focused)
    youtube_videos = []
    if active_doubt:
        try:
            youtube_videos = search_youtube_videos(active_doubt['question'], course=active_course)
        except Exception as exc:
            logger.warning("DOUBT_SOLVER: YouTube search failed: %s", exc)

    # Fetch history (last 20 queries) — filtered by active course
    cursor.execute("""
        SELECT id, question, created_at, pdf_name, page_number, subject
        FROM ai_doubt_history
        WHERE user_id=?
        ORDER BY created_at DESC
        LIMIT 20
    """, (user_id,))
    all_history = [dict(row) for row in cursor.fetchall()]
    # Filter history to show only doubts relevant to the active course
    history = [h for h in all_history if _matches_course(h.get('pdf_name', ''), h.get('subject', ''), active_course)]

    # Count of saved/bookmarked doubts
    cursor.execute("SELECT COUNT(*) FROM saved_answers WHERE user_id=?", (user_id,))
    saved_count = cursor.fetchone()[0]

    conn.close()
    return render_template(
        'doubt_solver.html',
        active_page='doubt_solver',
        user=user,
        active_doubt=active_doubt,
        youtube_videos=youtube_videos,
        history=history,
        saved_count=saved_count,
        active_course=active_course,
        has_gate=has_gate,
        has_neet=has_neet,
        both_courses=both_courses
    )

# Bookmark doubt route
@doubt_solver_bp.route('/bookmark/<int:doubt_id>', methods=['POST'])
def bookmark_doubt(doubt_id):
    user_email = session.get("user_email")
    if not user_email:
        return redirect(url_for('signin.signin_page'))

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE email=?", (user_email,))
    user = cursor.fetchone()

    if user:
        user_id = user['id']
        cursor.execute("SELECT * FROM ai_doubt_history WHERE id=? AND user_id=?", (doubt_id, user_id))
        doubt = cursor.fetchone()
        
        if doubt:
            # Check if already saved
            cursor.execute("SELECT COUNT(*) FROM saved_answers WHERE user_id=? AND question=?", (user_id, doubt['question']))
            exists = cursor.fetchone()[0]
            if exists == 0:
                cursor.execute("""
                    INSERT INTO saved_answers (user_id, question, answer, pdf_name, page_number, chapter, topic)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (user_id, doubt['question'], doubt['answer'], doubt['pdf_name'], doubt['page_number'], doubt['chapter'], doubt['topic']))
                conn.commit()
                flash("Doubt bookmarked successfully!", "success")
            else:
                flash("Doubt already bookmarked.", "info")
                
    conn.close()
    active_course = request.form.get('active_course', 'GATE').upper()
    return redirect(url_for('doubt_solver.solver_page', active_doubt_id=doubt_id, course=active_course))

# Saved Doubts Route
@doubt_solver_bp.route('/saved', methods=['GET'])
def saved_doubts():
    user_email = session.get("user_email")
    if not user_email:
        return redirect(url_for('signin.signin_page'))

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE email=?", (user_email,))
    user = cursor.fetchone()

    if not user:
        conn.close()
        return redirect(url_for('signin.signin_page'))

    user_id = user['id']
    cursor.execute("SELECT * FROM saved_answers WHERE user_id=? ORDER BY created_at DESC", (user_id,))
    saved_list = [dict(row) for row in cursor.fetchall()]
    
    # Parse json answers
    for item in saved_list:
        if item['answer'].startswith('{'):
            try:
                item['parsed_answer'] = json.loads(item['answer'])
            except Exception:
                item['parsed_answer'] = None
        else:
            item['parsed_answer'] = None

    conn.close()
    return render_template(
        'saved_doubts.html',
        active_page='doubt_solver',
        user=user,
        saved_list=saved_list
    )

# Delete doubt from history
@doubt_solver_bp.route('/delete/<int:doubt_id>', methods=['POST'])
def delete_doubt(doubt_id):
    user_email = session.get("user_email")
    if not user_email:
        return redirect(url_for('signin.signin_page'))

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE email=?", (user_email,))
    user = cursor.fetchone()

    if user:
        cursor.execute("DELETE FROM ai_doubt_history WHERE id=? AND user_id=?", (doubt_id, user['id']))
        conn.commit()
        flash("History entry deleted.", "success")
        
    conn.close()
    active_course = request.form.get('active_course', 'GATE').upper()
    return redirect(url_for('doubt_solver.solver_page', course=active_course))

# Clear all history
@doubt_solver_bp.route('/clear-history', methods=['POST'])
def clear_history():
    user_email = session.get("user_email")
    if not user_email:
        return redirect(url_for('signin.signin_page'))

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE email=?", (user_email,))
    user = cursor.fetchone()

    if user:
        cursor.execute("DELETE FROM ai_doubt_history WHERE user_id=?", (user['id'],))
        conn.commit()
        flash("Doubt solver history cleared.", "success")
        
    conn.close()
    active_course = request.form.get('active_course', 'GATE').upper()
    return redirect(url_for('doubt_solver.solver_page', course=active_course))

# Delete saved doubt
@doubt_solver_bp.route('/delete-saved/<int:saved_id>', methods=['POST'])
def delete_saved(saved_id):
    user_email = session.get("user_email")
    if not user_email:
        return redirect(url_for('signin.signin_page'))

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE email=?", (user_email,))
    user = cursor.fetchone()

    if user:
        cursor.execute("DELETE FROM saved_answers WHERE id=? AND user_id=?", (saved_id, user['id']))
        conn.commit()
        flash("Saved doubt deleted.", "success")
        
    conn.close()
    return redirect(url_for('doubt_solver.saved_doubts'))
