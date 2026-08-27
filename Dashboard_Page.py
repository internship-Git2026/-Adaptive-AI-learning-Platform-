from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from database import get_db
from datetime import datetime, timedelta

# ===== CREATE BLUEPRINT =====
dashboard_bp = Blueprint('dashboard', __name__, url_prefix='/dashboard')


# ===== DASHBOARD PAGE =====
@dashboard_bp.route('/', methods=['GET'])
def dashboard_page():
    """Render Dashboard"""
    user_email = session.get("user_email")
    if not user_email:
        flash("Please sign in first.", "info")
        return redirect(url_for('signin.signin_page'))

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE email = ?", (user_email,))
    user = cursor.fetchone()

    if not user:
        session.clear()
        return redirect(url_for('signin.signin_page'))

    user_name = user['name']
    selected_course = user['selected_course']
    badge_status = user['payment_status'] if user['payment_status'] else "NOT_PAID"

    # Fetch stats dynamically
    user_id = user['id']
    
    # Study Hours
    cursor.execute("SELECT SUM(duration_minutes) as total_min FROM study_sessions WHERE user_id=?", (user_id,))
    sh_row = cursor.fetchone()
    db_hours = round(sh_row['total_min'] / 60.0, 1) if sh_row and sh_row['total_min'] else 0
    study_hours = f"{db_hours:.1f}"    
    # ================= STUDY STREAK =================

    cursor.execute("""
        SELECT DISTINCT DATE(session_start) AS study_date
        FROM study_sessions
        WHERE user_id=?
        ORDER BY study_date DESC
    """, (user_id,))

    study_dates = {
        row["study_date"]
        for row in cursor.fetchall()
    }

    study_streak = 0

    today = datetime.now().date()

# If user didn't study today,
# start checking from yesterday
    if today.strftime("%Y-%m-%d") not in study_dates:
        today = today - timedelta(days=1)

    while today.strftime("%Y-%m-%d") in study_dates:

        study_streak += 1

        today = today - timedelta(days=1)
    
    # Questions Solved
    cursor.execute("SELECT SUM(total_questions) as total_q FROM quiz_results WHERE user_id=?", (user_id,))
    qs_row = cursor.fetchone()
    db_solved = qs_row['total_q'] if qs_row and qs_row['total_q'] else 0
    questions_solved = f"{db_solved:,}"
    # Accuracy
    cursor.execute("SELECT AVG(percentage) as average FROM quiz_results WHERE user_id=?", (user_id,))
    acc_row = cursor.fetchone()
    db_accuracy = round(acc_row['average']) if acc_row and acc_row['average'] else 0
    accuracy = f"{db_accuracy}%"    
        
    # Recent Activity
    cursor.execute("""
        SELECT * FROM recent_activity 
        WHERE user_id=? 
        ORDER BY activity_time DESC 
        LIMIT 4
    """, (user_id,))
    activities = cursor.fetchall()
    
    ICON_MAP = {
      "pdf": "fa-file-pdf",
      "quiz": "fa-robot",
      "profile": "fa-user-pen",
      "course": "fa-book",
      "practice": "fa-pencil"
    }
    COLOR_MAP = {
      "pdf": "pdf-color",
      "quiz": "quiz-color",
      "profile": "profile-color",
      "course": "course-color",
      "practice": "practice-color"
    }
    
    recent_activity = []
    for act in activities:
        recent_activity.append({
            "title": act["activity_title"],
            "description": act["activity_description"],
            "time": act["activity_time"],
            "icon": ICON_MAP.get(act["activity_type"], "fa-circle"),
            "color": COLOR_MAP.get(act["activity_type"], "default-color")
        })

    # If no activity in database, add some mock learning activities
    if not recent_activity:
        recent_activity = [
          {
            "title": "No Recent Activity",
            "description": "Start by uploading a PDF or taking an AI quiz.",
            "time": "",
            "icon": "fa-clock",
            "color": "default-color"
          }
    ]
    
    # ================= DAILY GOAL =================

    DAILY_GOAL_MINUTES = 120

    cursor.execute("""
        SELECT COALESCE(SUM(duration_minutes),0) AS total
        FROM study_sessions
        WHERE user_id=?
        AND DATE(session_start)=DATE('now')
    """, (user_id,))

    today_minutes = cursor.fetchone()["total"]

    goal_percentage = min(
        round((today_minutes / DAILY_GOAL_MINUTES) * 100),
        100
    )

    remaining_minutes = max(
        DAILY_GOAL_MINUTES - today_minutes,
        0
    )

    # Weekly Study Progress data (last 7 days mapping)
    cursor.execute("""
        SELECT strftime('%w', session_start) as day_num, SUM(duration_minutes) as duration
        FROM study_sessions
        WHERE user_id=? AND session_start >= datetime('now', '-7 days')
        GROUP BY day_num
    """, (user_id,))
    sessions = cursor.fetchall()
    day_mapping = {0: "Sun", 1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat"}
    study_dict = {day: 0.0 for day in day_mapping.values()}
    for s in sessions:
        day_name = day_mapping[int(s['day_num'])]
        study_dict[day_name] = round(s['duration'] / 60.0, 1)
        
    weekly_study_data = [{"day": day, "hours": study_dict[day]} for day in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]]
    
    current_hour = datetime.now().hour

    if current_hour < 12:
        greeting = "Good Morning"
    elif current_hour < 17:
        greeting = "Good Afternoon"
    else:
        greeting = "Good Evening" 

    # Fetch recent notifications (latest 5)
    from notifications import get_recent_notifications, format_notification_time
    raw_notifications = get_recent_notifications(user_id, limit=5)
    recent_notifications = []
    for n in raw_notifications:
        item = dict(n)
        item["display_time"] = format_notification_time(n["created_at"])
        recent_notifications.append(item)

    # Fetch recent AI Doubts
    cursor.execute("""
        SELECT * FROM ai_doubt_history
        WHERE user_id=?
        ORDER BY created_at DESC
        LIMIT 5
    """, (user_id,))
    recent_doubts = [dict(row) for row in cursor.fetchall()]

    conn.close()

    return render_template(
    'Dashboard_page.html',

    active_page='dashboard',

    user_name=user_name,

    greeting=greeting,

    study_hours=study_hours,

    questions_solved=questions_solved,

    accuracy=accuracy,
    
    recommendation_text=None,

    selected_course=selected_course,

    badge_status=badge_status,

    recent_activity=recent_activity,

    goal_percentage=goal_percentage,

    today_minutes=today_minutes,

    remaining_minutes=remaining_minutes,

    daily_goal=DAILY_GOAL_MINUTES,

    study_streak=study_streak,

    weekly_study_data=weekly_study_data,
    
    recent_notifications=recent_notifications,
    
    recent_doubts=recent_doubts
)

# ===== UPDATE STATS =====
@dashboard_bp.route('/update-stats', methods=['POST'])
def update_stats():
    print("Dashboard stats updated!")
    return redirect(url_for('dashboard.dashboard_page'))


# ===== START QUIZ =====
@dashboard_bp.route('/start-quiz', methods=['POST'])
def start_quiz():
    print("Starting Quiz...")
    # Get user course choice to redirect to correct quiz theme
    user_email = session.get("user_email")
    course = 'GATE'
    if user_email:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT selected_course FROM users WHERE email = ?", (user_email,))
        user = cursor.fetchone()
        conn.close()
        if user and user['selected_course'] and user['selected_course'] != 'GATE+NEET':
            course = user['selected_course']
    return redirect(url_for('quiz.ai_quiz', course=course))


# ===== PROFILE =====
@dashboard_bp.route('/profile')
def profile():
    return redirect(url_for('profile.profile_page'))