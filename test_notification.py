from notifications import create_notification

create_notification(
    user_id=2,   # <-- Your logged-in user
    title="Quiz Completed",
    message="You scored 92% in DBMS Quiz.",
    category="success",
    source="quiz",
    action_url="/progress",
    icon="🧠"
)

print("Notification Created Successfully")