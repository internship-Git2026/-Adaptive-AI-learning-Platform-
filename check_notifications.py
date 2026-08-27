import sqlite3
from database import DB_PATH

conn = sqlite3.connect(DB_PATH)

cursor = conn.cursor()

cursor.execute("SELECT * FROM notifications")

rows = cursor.fetchall()

for row in rows:
    print(row)

conn.close()