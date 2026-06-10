import sqlite3
from datetime import datetime

DB_PATH = "beauty_bot.db"


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS clients (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            service_id TEXT,
            date TEXT,
            time TEXT,
            name TEXT,
            phone TEXT,
            status TEXT DEFAULT 'active',
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES clients(user_id)
        );

        CREATE TABLE IF NOT EXISTS scheduled_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT,
            photo TEXT,
            scheduled_at TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT (datetime('now'))
        );
    """)
    conn.commit()
    conn.close()


def add_client(user_id: int, username: str, first_name: str):
    conn = get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO clients (user_id, username, first_name) VALUES (?, ?, ?)",
        (user_id, username, first_name)
    )
    conn.commit()
    conn.close()


def get_all_clients():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM clients").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def create_booking(user_id, service_id, date, time, name, phone):
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO bookings (user_id, service_id, date, time, name, phone) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, service_id, date, time, name, phone)
    )
    booking_id = cur.lastrowid
    conn.commit()
    conn.close()
    return booking_id


def get_booked_times(date: str):
    conn = get_conn()
    rows = conn.execute(
        "SELECT time FROM bookings WHERE date=? AND status='active'", (date,)
    ).fetchall()
    conn.close()
    return [r['time'] for r in rows]


def get_client_bookings(user_id: int):
    today = datetime.now().strftime("%Y-%m-%d")
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM bookings WHERE user_id=? AND date>=? AND status='active' ORDER BY date, time",
        (user_id, today)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_bookings_by_date(date: str):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM bookings WHERE date=? AND status='active' ORDER BY time",
        (date,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_upcoming_bookings(from_date: str):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM bookings WHERE date>=? AND status='active' ORDER BY date, time",
        (from_date,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def save_scheduled_post(text: str, photo: str, scheduled_at: str) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO scheduled_posts (text, photo, scheduled_at) VALUES (?, ?, ?)",
        (text, photo, scheduled_at)
    )
    post_id = cur.lastrowid
    conn.commit()
    conn.close()
    return post_id


def get_scheduled_posts():
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM scheduled_posts WHERE status='pending' ORDER BY scheduled_at"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_post_sent(post_id: int):
    conn = get_conn()
    conn.execute(
        "UPDATE scheduled_posts SET status='sent' WHERE id=?", (post_id,)
    )
    conn.commit()
    conn.close()


def save_broadcast_messages(sent_messages: list) -> int:
    """Зберігає список (user_id, message_id) і повертає broadcast_id"""
    import json
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS broadcasts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            messages TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    cur = conn.execute(
        "INSERT INTO broadcasts (messages) VALUES (?)",
        (json.dumps(sent_messages),)
    )
    broadcast_id = cur.lastrowid
    conn.commit()
    conn.close()
    return broadcast_id


def get_broadcast_messages(broadcast_id: int) -> list:
    import json
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS broadcasts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            messages TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    row = conn.execute(
        "SELECT messages FROM broadcasts WHERE id=?", (broadcast_id,)
    ).fetchone()
    conn.close()
    if not row:
        return []
    return json.loads(row['messages'])


def delete_broadcast_messages(broadcast_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM broadcasts WHERE id=?", (broadcast_id,))
    conn.commit()
    conn.close()
