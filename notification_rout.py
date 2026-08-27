from flask import Blueprint, render_template, session, redirect, url_for, request
from database import get_db

from notifications import (
    get_notifications,
    get_unread_count,
    mark_all_read,
    mark_as_read,
    delete_notification,
    format_notification_time
)

notification_bp = Blueprint(
    "notification",
    __name__
)

def get_session_user_id():
    """Retrieve user_id from session or restore it using user_email."""
    user_id = session.get("user_id")
    if user_id:
        return user_id
    user_email = session.get("user_email")
    if user_email:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE email = ?", (user_email,))
        user = cursor.fetchone()
        conn.close()
        if user:
            session["user_id"] = user["id"]
            return user["id"]
    return None


@notification_bp.route("/notifications")
def notifications_page():

    user_id = get_session_user_id()
    if not user_id:
        return redirect(url_for("signin.signin_page"))

    # Filter (all / unread / read)
    status = request.args.get("status", "all")

    notifications = get_notifications(
        user_id=user_id,
        status=status
    )

    formatted_notifications = []

    for notification in notifications:

        item = dict(notification)

        item["display_time"] = format_notification_time(
            notification["created_at"]
        )

        formatted_notifications.append(item)

    unread_count = get_unread_count(user_id)

    return render_template(
        "notifications.html",
        notifications=formatted_notifications,
        unread_count=unread_count,
        status=status,
        active_page="notifications"
    )


@notification_bp.route("/notifications/read-all")
def read_all():

    user_id = get_session_user_id()
    if not user_id:
        return redirect(url_for("signin.signin_page"))

    mark_all_read(user_id)

    return redirect(url_for("notification.notifications_page"))


@notification_bp.route("/notifications/read/<int:notification_id>")
def read_one(notification_id):

    user_id = get_session_user_id()
    if not user_id:
        return redirect(url_for("signin.signin_page"))

    mark_as_read(notification_id, user_id)

    return redirect(url_for("notification.notifications_page"))


@notification_bp.route("/notifications/delete/<int:notification_id>")
def delete_one(notification_id):

    user_id = get_session_user_id()
    if not user_id:
        return redirect(url_for("signin.signin_page"))

    delete_notification(notification_id, user_id)

    return redirect(url_for("notification.notifications_page"))