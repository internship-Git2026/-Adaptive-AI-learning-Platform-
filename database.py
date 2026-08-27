import os
import sqlite3
from datetime import datetime

# Define absolute DB path relative to this script directory
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "database.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def create_tables():
    conn = get_db()
    cursor = conn.cursor()

    # ---------------- USERS TABLE ---------------- #
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,

        phone TEXT DEFAULT '',
        college TEXT DEFAULT '',
        department TEXT DEFAULT '',
        year TEXT DEFAULT '',

        selected_course TEXT DEFAULT NULL,
        payment_plan INTEGER DEFAULT NULL,
        payment_status TEXT DEFAULT 'NOT_PAID',
        trial_used INTEGER DEFAULT 0,
        trial_credits INTEGER DEFAULT 1,
        enrolled_at TEXT DEFAULT NULL
    )
    """)

    # ---------------- UPLOADED PDF TABLE ---------------- #
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS uploaded_pdfs(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        course TEXT NOT NULL,
        pdf_name TEXT NOT NULL,
        file_path TEXT NOT NULL,
        upload_time TEXT NOT NULL,
        pdf_type TEXT NOT NULL,
        total_pages INTEGER,
        word_count INTEGER,
        character_count INTEGER,
        extracted_text TEXT,
        status TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)

    # ---------------- QUIZ QUESTIONS TABLE ---------------- #
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS quiz_questions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pdf_id INTEGER NOT NULL,
        question TEXT NOT NULL,
        option1 TEXT NOT NULL,
        option2 TEXT NOT NULL,
        option3 TEXT NOT NULL,
        option4 TEXT NOT NULL,
        correct_answer INTEGER NOT NULL,
        explanation TEXT,
        FOREIGN KEY(pdf_id) REFERENCES uploaded_pdfs(id)
    )
    """)

    # ---------- CHECK FOR MISSING QUIZ_QUESTIONS COLUMNS ---------- #
    cursor.execute("PRAGMA table_info(quiz_questions)")
    qq_columns = [col[1] for col in cursor.fetchall()]
    if "topic" not in qq_columns:
        cursor.execute("ALTER TABLE quiz_questions ADD COLUMN topic TEXT DEFAULT 'General'")
    if "difficulty_level" not in qq_columns:
        cursor.execute("ALTER TABLE quiz_questions ADD COLUMN difficulty_level TEXT DEFAULT 'Medium'")

    # ---------------- QUIZ RESULTS TABLE ---------------- #
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS quiz_results(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        pdf_id INTEGER NOT NULL,
        score INTEGER,
        total_questions INTEGER,
        percentage REAL,
        completed_at TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id),
        FOREIGN KEY(pdf_id) REFERENCES uploaded_pdfs(id)
    )
    """)
    # ---------------- QUESTION ATTEMPTS TABLE ---------------- #
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS question_attempts(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        question_id INTEGER,
        topic TEXT DEFAULT 'General',
        was_correct INTEGER NOT NULL,
        answered_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)

    # ---------------- USER COURSES TABLE ---------------- #
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_courses(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        course_name TEXT NOT NULL,
        course_category TEXT,
        payment_plan INTEGER,
        payment_status TEXT DEFAULT 'PAID',
        purchased_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)

# ---------------- RECENT ACTIVITY TABLE ---------------- #
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS recent_activity(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,

        activity_type TEXT NOT NULL,

        activity_title TEXT NOT NULL,

        activity_description TEXT,

        activity_time TEXT DEFAULT CURRENT_TIMESTAMP,

        FOREIGN KEY(user_id) REFERENCES users(id)
    )
""")

        # ---------------- STUDY SESSIONS TABLE ---------------- #
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS study_sessions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        course TEXT,
        session_start TEXT NOT NULL,
        session_end TEXT,
        duration_minutes INTEGER DEFAULT 0,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)

    # ---------------- GUEST TRIALS TABLE ---------------- #
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS guest_trials(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trial_id TEXT UNIQUE NOT NULL,
        browser_token TEXT UNIQUE NOT NULL,
        course TEXT NOT NULL,
        pdf_credit INTEGER DEFAULT 1,
        quiz_credit INTEGER DEFAULT 1,
        trial_used INTEGER DEFAULT 0,
        pdf_uploaded INTEGER DEFAULT 0,
        quiz_generated INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # ---------------- CHECK FOR MISSING GUEST_TRIALS COLUMNS ---------------- #
    cursor.execute("PRAGMA table_info(guest_trials)")
    trial_columns = [col[1] for col in cursor.fetchall()]
    if "fingerprint" not in trial_columns:
        cursor.execute("ALTER TABLE guest_trials ADD COLUMN fingerprint TEXT DEFAULT NULL")
    if "ip" not in trial_columns:
        cursor.execute("ALTER TABLE guest_trials ADD COLUMN ip TEXT DEFAULT NULL")

    # ---------------- AUTH ATTEMPT / LOCKOUT TABLE ---------------- #
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS auth_attempts(
        identifier TEXT NOT NULL,
        ip TEXT NOT NULL,
        fail_count INTEGER DEFAULT 0,
        locked_until TEXT DEFAULT NULL,
        last_failed_at TEXT DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (identifier, ip)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        message TEXT NOT NULL,
        type TEXT NOT NULL,
        icon TEXT DEFAULT '🔔',
        is_read INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)

    # ---------------- CHECK FOR MISSING UPLOADED_PDFS COLUMNS ---------------- #
    cursor.execute("PRAGMA table_info(uploaded_pdfs)")
    pdf_columns = [col[1] for col in cursor.fetchall()]
    if "trial_id" not in pdf_columns:
        cursor.execute("ALTER TABLE uploaded_pdfs ADD COLUMN trial_id TEXT DEFAULT NULL")

    # ---------------- CHECK FOR MISSING QUIZ_RESULTS COLUMNS ---------------- #
    cursor.execute("PRAGMA table_info(quiz_results)")
    result_columns = [col[1] for col in cursor.fetchall()]
    if "trial_id" not in result_columns:
        cursor.execute("ALTER TABLE quiz_results ADD COLUMN trial_id TEXT DEFAULT NULL")

    # ---------------- CHECK FOR MISSING USER COLUMNS ---------------- #
    cursor.execute("PRAGMA table_info(users)")
    columns = [col[1] for col in cursor.fetchall()]

    new_cols = {

    'phone': "TEXT DEFAULT ''",
    'college': "TEXT DEFAULT ''",
    'department': "TEXT DEFAULT ''",
    'year': "TEXT DEFAULT ''",

    'selected_course': "TEXT DEFAULT NULL",
    'payment_plan': "INTEGER DEFAULT NULL",
    'payment_status': "TEXT DEFAULT 'NOT_PAID'",
    'trial_used': "INTEGER DEFAULT 0",
    'trial_credits': "INTEGER DEFAULT 1",
    'enrolled_at': "TEXT DEFAULT NULL"

}

    for col_name, col_type in new_cols.items():
        if col_name not in columns:
            cursor.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_type}")


    # ---------------- CHECK FOR MISSING RECENT ACTIVITY COLUMN ---------------- #

    cursor.execute("PRAGMA table_info(recent_activity)")
    activity_columns = [col[1] for col in cursor.fetchall()]

    if "activity_description" not in activity_columns:
        cursor.execute("""
        ALTER TABLE recent_activity
        ADD COLUMN activity_description TEXT
    """)
    
    # ---------------- CHECK FOR MISSING NOTIFICATION COLUMNS ---------------- #

    cursor.execute("PRAGMA table_info(notifications)")
    notification_columns = [col[1] for col in cursor.fetchall()]

    new_notification_columns = {
        "category": "TEXT DEFAULT 'info'",
        "source": "TEXT DEFAULT 'system'",
        "action_url": "TEXT DEFAULT NULL"
    }

    for col_name, col_type in new_notification_columns.items():
        if col_name not in notification_columns:
          cursor.execute(
            f"ALTER TABLE notifications ADD COLUMN {col_name} {col_type}"
        )

    # ---------------- STUDY_PLAN TABLE ---------------- #
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS study_plan (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        date TEXT NOT NULL,
        subject TEXT NOT NULL,
        topic TEXT NOT NULL,
        recommended_minutes INTEGER NOT NULL,
        priority TEXT NOT NULL,
        difficulty TEXT DEFAULT 'Medium',
        plan_type TEXT DEFAULT 'today',
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)

    # ---------------- REVISION_SCHEDULE TABLE ---------------- #
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS revision_schedule (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        pdf_id INTEGER,
        subject TEXT NOT NULL,
        topic TEXT NOT NULL,
        priority TEXT DEFAULT 'Medium',
        mastery_score INTEGER DEFAULT 0,
        wrong_answers INTEGER DEFAULT 0,
        revision_count INTEGER DEFAULT 0,
        interval_days INTEGER DEFAULT 1,
        next_revision TEXT NOT NULL,
        last_revision TEXT,
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id),
        FOREIGN KEY(pdf_id) REFERENCES uploaded_pdfs(id)
    )
    """)

    # ---------------- UPLOADED_PDF_PAGES TABLE ---------------- #
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS uploaded_pdf_pages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pdf_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        page_number INTEGER NOT NULL,
        page_text TEXT NOT NULL,
        embedding TEXT,
        embedding_model TEXT DEFAULT NULL,
        FOREIGN KEY(pdf_id) REFERENCES uploaded_pdfs(id),
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)

    # ---------- CHECK FOR MISSING UPLOADED_PDF_PAGES COLUMNS ---------- #
    cursor.execute("PRAGMA table_info(uploaded_pdf_pages)")
    page_columns = [col[1] for col in cursor.fetchall()]
    if "embedding_model" not in page_columns:
        cursor.execute("ALTER TABLE uploaded_pdf_pages ADD COLUMN embedding_model TEXT DEFAULT NULL")

    # ---------------- AI_DOUBT_HISTORY TABLE ---------------- #
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ai_doubt_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        question TEXT NOT NULL,
        answer TEXT NOT NULL,
        pdf_name TEXT,
        page_number TEXT,
        chapter TEXT,
        topic TEXT,
        subject TEXT DEFAULT 'General',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)

    # ---------------- SAVED_ANSWERS TABLE ---------------- #
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS saved_answers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        question TEXT NOT NULL,
        answer TEXT NOT NULL,
        pdf_name TEXT,
        page_number TEXT,
        chapter TEXT,
        topic TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)

    # ---------------- CHECK FOR MISSING USER GOOGLE COLUMN ---------------- #
    cursor.execute("PRAGMA table_info(users)")
    user_columns = [col[1] for col in cursor.fetchall()]
    if "google_id" not in user_columns:
        cursor.execute("ALTER TABLE users ADD COLUMN google_id TEXT")

    # ---------------- CHECK FOR MISSING STUDY_PLAN COLUMNS ---------------- #
    cursor.execute("PRAGMA table_info(study_plan)")
    plan_columns = [col[1] for col in cursor.fetchall()]
    if "difficulty" not in plan_columns:
        cursor.execute("ALTER TABLE study_plan ADD COLUMN difficulty TEXT DEFAULT 'Medium'")
    if "plan_type" not in plan_columns:
        cursor.execute("ALTER TABLE study_plan ADD COLUMN plan_type TEXT DEFAULT 'today'")

    # ---------------- BACKFILL USER COURSES ----------------
    # Existing paid users predate the user_courses record keeping.
    # Backfill a verified PAID user_courses row for each user whose
    # payment_status is already PAID so no valid access is lost.
    # (No existing user_courses data exists, but checks keep it idempotent.)
    backfill_price_map = {
        'GATE': 1000,
        'NEET': 1000,
        'GATE+NEET': 1500
    }
    cursor.execute("""
        SELECT id, selected_course, payment_plan, enrolled_at
        FROM users
        WHERE payment_status = 'PAID' AND selected_course IN ('GATE', 'NEET', 'GATE+NEET')
    """)
    paid_users = cursor.fetchall()

    for row in paid_users:
        course_name = row['selected_course']
        cursor.execute(
            "SELECT 1 FROM user_courses WHERE user_id = ? AND course_name = ?",
            (row['id'], course_name)
        )
        if cursor.fetchone():
            continue

        payment_plan = row['payment_plan'] or backfill_price_map.get(course_name)
        purchased_at = row['enrolled_at'] or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("""
            INSERT INTO user_courses (user_id, course_name, payment_plan, payment_status, purchased_at)
            VALUES (?, ?, ?, 'PAID', ?)
        """, (row['id'], course_name, payment_plan, purchased_at))

    conn.commit()
    conn.close()


# Create all tables automatically when this file is imported
create_tables()