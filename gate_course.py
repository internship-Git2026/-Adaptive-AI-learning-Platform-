from flask import Blueprint, render_template, redirect, url_for, session, flash
from database import get_db
from course_access import has_course_access

gate_course_bp = Blueprint('gate_course', __name__, url_prefix='/dashboard/gate')

# GATE subjects with their PDF keyword patterns and metadata
GATE_SUBJECTS = [
    {
        "key": "data_structures",
        "name": "Data Structures & Algorithms",
        "description": "Sorting, Trees, Graphs, Complexity Analysis, Hashing",
        "icon": "fas fa-code",
        "keywords": ["data structure", "algorithm", "sorting", "tree", "graph", "hashing", "complexity"]
    },
    {
        "key": "os",
        "name": "Operating Systems",
        "description": "Process Management, Semaphores, Deadlocks, Virtual Memory",
        "icon": "fas fa-desktop",
        "keywords": ["operating system", "process", "semaphore", "deadlock", "virtual memory", "scheduling"]
    },
    {
        "key": "dbms",
        "name": "Database Management Systems",
        "description": "SQL, Normalization, Transactions, ER Diagrams",
        "icon": "fas fa-database",
        "keywords": ["database", "sql", "normalization", "transaction", "er diagram", "dbms"]
    },
    {
        "key": "networks",
        "name": "Computer Networks",
        "description": "TCP/IP Suite, Routing Algorithms, Socket Programming, OSI Layer",
        "icon": "fas fa-network-wired",
        "keywords": ["network", "tcp", "ip", "routing", "osi", "socket", "protocol"]
    },
    {
        "key": "toc",
        "name": "Theory of Computation",
        "description": "Automata, Grammars, Turing Machines, Computability",
        "icon": "fas fa-project-diagram",
        "keywords": ["automata", "grammar", "turing", "computation", "finite", "pushdown", "regex"]
    },
    {
        "key": "compiler",
        "name": "Compiler Design",
        "description": "Lexical Analysis, Parsing, Code Generation, Optimization",
        "icon": "fas fa-cogs",
        "keywords": ["compiler", "lexical", "parsing", "grammar", "code generation", "syntax"]
    },
    {
        "key": "discrete",
        "name": "Discrete Mathematics",
        "description": "Logic, Sets, Graph Theory, Combinatorics, Probability",
        "icon": "fas fa-square-root-alt",
        "keywords": ["discrete", "logic", "set", "combinatorics", "probability", "permutation", "graph theory"]
    },
    {
        "key": "digital",
        "name": "Digital Logic & Architecture",
        "description": "Boolean Algebra, Logic Gates, Flip-Flops, Pipelines",
        "icon": "fas fa-microchip",
        "keywords": ["digital", "boolean", "logic gate", "flip flop", "pipeline", "cpu", "architecture"]
    },
]


# NEET subjects with their PDF keyword patterns and metadata
NEET_SUBJECTS = [
    {
        "key": "biology",
        "name": "Biology — Zoology & Botany",
        "description": "Genetics, Human Physiology, Plant Reproduction, Cell Biology, Ecology",
        "icon": "fas fa-leaf",
        "keywords": ["biology", "zoology", "botany", "genetics", "physiology", "plant reproduction", "cell biology", "ecology", "human physiology"]
    },
    {
        "key": "chemistry",
        "name": "Chemistry",
        "description": "Organic Chemistry, Periodic Table, Chemical Bonding, Equilibrium",
        "icon": "fas fa-flask",
        "keywords": ["chemistry", "organic", "periodic table", "chemical bonding", "equilibrium"]
    },
    {
        "key": "physics",
        "name": "Physics",
        "description": "Thermodynamics, Optics, Kinematics, Modern Physics, Mechanics",
        "icon": "fas fa-atom",
        "keywords": ["physics", "thermodynamics", "optics", "kinematics", "modern physics", "mechanics"]
    },
]


def _build_subject_progress(subject_defs, results):
    """Accumulate quiz score/total per subject and derive status labels."""
    subject_data = {s["key"]: {"scores": [], "totals": []} for s in subject_defs}

    for row in results:
        pdf_name_lower = (row["pdf_name"] or "").lower()
        course_lower = (row["course"] or "").lower()
        combined = pdf_name_lower + " " + course_lower

        for subject in subject_defs:
            for kw in subject["keywords"]:
                if kw in combined:
                    subject_data[subject["key"]]["scores"].append(row["score"])
                    subject_data[subject["key"]]["totals"].append(row["total_questions"])
                    break  # matched this subject, don't double-count

    subjects_out = []
    for subject in subject_defs:
        key = subject["key"]
        scores = subject_data[key]["scores"]
        totals = subject_data[key]["totals"]

        if totals and sum(totals) > 0:
            pct = round((sum(scores) / sum(totals)) * 100)
        else:
            pct = 0

        # Determine status label and CSS class
        if pct >= 70:
            status_label = f"{pct}% Complete"
            status_class = "complete"
        elif pct >= 30:
            status_label = f"{pct}% In Progress"
            status_class = "in-progress"
        elif pct > 0:
            status_label = f"{pct}% Started"
            status_class = "low"
        else:
            status_label = "Not Started"
            status_class = "not-started"

        subjects_out.append({
            "key": subject["key"],
            "name": subject["name"],
            "description": subject["description"],
            "icon": subject["icon"],
            "pct": pct,
            "status_label": status_label,
            "status_class": status_class,
        })

    return subjects_out


def _get_subject_progress(user_id, subject_defs):
    """Load a user's quiz results and compute per-subject progress."""
    conn = get_db()
    cursor = conn.cursor()

    # Get all quiz results for this user with the PDF name
    cursor.execute("""
        SELECT qr.score, qr.total_questions, qr.percentage,
               p.pdf_name, p.course
        FROM quiz_results qr
        JOIN uploaded_pdfs p ON qr.pdf_id = p.id
        WHERE qr.user_id = ?
    """, (user_id,))
    results = cursor.fetchall()
    conn.close()

    return _build_subject_progress(subject_defs, results)


def get_subject_progress(user_id):
    """
    Calculate per-subject progress for a user from their quiz results.
    Matches PDF names/courses to known GATE subjects by keyword.
    Returns list of subject dicts with pct, status_label, status_class.
    """
    return _get_subject_progress(user_id, GATE_SUBJECTS)


def get_neet_subject_progress(user_id):
    """Per-subject progress for NEET subjects (Biology, Chemistry, Physics)."""
    return _get_subject_progress(user_id, NEET_SUBJECTS)


@gate_course_bp.route('/')
def gate_course_page():
    user_email = session.get("user_email")
    if not user_email:
        return redirect(url_for('signin.signin_page'))

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE email = ?", (user_email,))
    user = cursor.fetchone()
    conn.close()

    if not user or user['payment_status'] != 'PAID':
        return redirect(url_for('plans.plans_page'))

    if not has_course_access(user['id'], 'GATE'):
        flash("You are not enrolled in the GATE course. Please purchase the course to access.", "warning")
        return redirect(url_for('my_courses.my_courses_page'))

    subjects = get_subject_progress(user['id'])

    return render_template('gate_course.html', subjects=subjects)
