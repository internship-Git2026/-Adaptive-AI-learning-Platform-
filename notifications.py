import sqlite3
from database import DB_PATH
from datetime import datetime

def create_notification(
    user_id,
    title,
    message,
    category="info",
    source="system",
    action_url=None,
    icon="🔔"
):
    """
    Generic notification creator.
    Every module should use this function.
    """

    # Resolve icon based on category
    CATEGORY_ICONS = {
        'quiz': '📝',
        'course': '📚',
        'achievement': '🏆',
        'reminder': '⚠',
        'system': '🔔',
        'trial': '⏳',
        'progress': '📈'
    }
    if icon == "🔔" and category.lower() in CATEGORY_ICONS:
        icon = CATEGORY_ICONS[category.lower()]

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO notifications
        (
            user_id,
            title,
            message,
            type,
            icon,
            category,
            source,
            action_url
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        user_id,
        title,
        message,
        source,
        icon,
        category,
        source,
        action_url
    ))

    conn.commit()
    conn.close()


def get_notifications(user_id, status="all"):
    """
    Get notifications by status.
    """

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    query = """
        SELECT *
        FROM notifications
        WHERE user_id=?
    """

    params = [user_id]

    if status == "unread":
        query += " AND is_read=0"

    elif status == "read":
        query += " AND is_read=1"

    query += " ORDER BY is_read ASC, created_at DESC"

    cursor.execute(query, params)

    notifications = cursor.fetchall()

    conn.close()

    return notifications


def get_unread_count(user_id):
    """
    Get unread notification count.
    """

    conn = sqlite3.connect(DB_PATH)

    cursor = conn.cursor()

    cursor.execute("""
        SELECT COUNT(*)
        FROM notifications
        WHERE user_id=?
        AND is_read=0
    """, (user_id,))

    count = cursor.fetchone()[0]

    conn.close()

    return count


def mark_as_read(notification_id, user_id):
    """
    Mark one notification as read (owned by the user).
    """

    conn = sqlite3.connect(DB_PATH)

    cursor = conn.cursor()

    cursor.execute("""
        UPDATE notifications
        SET is_read=1
        WHERE id=? AND user_id=?
    """, (notification_id, user_id))

    conn.commit()
    conn.close()


def mark_all_read(user_id):
    """
    Mark all notifications as read.
    """

    conn = sqlite3.connect(DB_PATH)

    cursor = conn.cursor()

    cursor.execute("""
        UPDATE notifications
        SET is_read=1
        WHERE user_id=?
    """, (user_id,))

    conn.commit()
    conn.close()


def delete_notification(notification_id, user_id):
    """
    Delete one notification (owned by the user).
    """

    conn = sqlite3.connect(DB_PATH)

    cursor = conn.cursor()

    cursor.execute("""
        DELETE FROM notifications
        WHERE id=? AND user_id=?
    """, (notification_id, user_id))

    conn.commit()
    conn.close()

def get_recent_notifications(user_id, limit=5):
    """
    Get the most recent notifications.
    """

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    cursor = conn.cursor()

    cursor.execute("""
        SELECT *
        FROM notifications
        WHERE user_id=?
        ORDER BY created_at DESC
        LIMIT ?
    """, (user_id, limit))

    notifications = cursor.fetchall()

    conn.close()

    return notifications

def has_unread_notifications(user_id):
    """
    Returns True if user has unread notifications.
    """

    return get_unread_count(user_id) > 0

def format_notification_time(created_at):
    """
    Convert database timestamp into
    '2 minutes ago', '5 days ago', etc.
    """

    if not created_at:
        return ""

    # SQLite timestamp format
    notification_time = datetime.strptime(
        created_at,
        "%Y-%m-%d %H:%M:%S"
    )

    now = datetime.utcnow() 

    diff = now - notification_time

    seconds = int(diff.total_seconds())

    if seconds < 60:
        return "Just now"

    minutes = seconds // 60

    if minutes == 1:
        return "1 minute ago"

    if minutes < 60:
        return f"{minutes} minutes ago"

    hours = minutes // 60

    if hours == 1:
        return "1 hour ago"

    if hours < 24:
        return f"{hours} hours ago"

    days = hours // 24

    if days == 1:
        return "1 day ago"

    if days < 30:
        return f"{days} days ago"

    months = days // 30

    if months == 1:
        return "1 month ago"

    if months < 12:
        return f"{months} months ago"

    years = months // 12

    if years == 1:
        return "1 year ago"

    return f"{years} years ago"