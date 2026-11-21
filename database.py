import os
import json
import libsql_client
from datetime import datetime

TURSO_URL = os.getenv("TURSO_DATABASE_URL", "")
TURSO_TOKEN = os.getenv("TURSO_AUTH_TOKEN", "")


def _client():
    return libsql_client.create_client_sync(url=TURSO_URL, auth_token=TURSO_TOKEN)


def _rows_to_dicts(result):
    cols = list(result.columns)
    return [dict(zip(cols, row)) for row in result.rows]


def init_db():
    with _client() as c:
        c.batch([
            """CREATE TABLE IF NOT EXISTS clients (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )""",
            """CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                service_id TEXT,
                date TEXT,
                time TEXT,
                name TEXT,
                phone TEXT,
                status TEXT DEFAULT 'active',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )""",
            """CREATE TABLE IF NOT EXISTS scheduled_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT,
                photo TEXT,
                scheduled_at TEXT,
                status TEXT DEFAULT 'pending',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )""",
            """CREATE TABLE IF NOT EXISTS broadcasts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                messages TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )""",
            """CREATE TABLE IF NOT EXISTS blocked_slots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                time TEXT,
                UNIQUE(date, time)
            )""",
        ])


def add_client(user_id: int, username: str, first_name: str):
    with _client() as c:
        c.execute(
            "INSERT INTO clients (user_id, username, first_name) VALUES (?, ?, ?) ON CONFLICT(user_id) DO NOTHING",
            (user_id, username, first_name),
        )


def get_all_clients():
    with _client() as c:
        return _rows_to_dicts(c.execute("SELECT * FROM clients"))


def create_booking(user_id, service_id, date, time, name, phone):
    with _client() as c:
        r = c.execute(
            "INSERT INTO bookings (user_id, service_id, date, time, name, phone) VALUES (?,?,?,?,?,?)",
            (user_id, service_id, date, time, name, phone),
        )
        return r.last_insert_rowid


def get_booked_times(date: str):
    with _client() as c:
        r = c.execute("SELECT time FROM bookings WHERE date=? AND status='active'", (date,))
        return [row[0] for row in r.rows]


def get_client_bookings(user_id: int):
    today = datetime.now().strftime("%Y-%m-%d")
    with _client() as c:
        r = c.execute(
            "SELECT * FROM bookings WHERE user_id=? AND date>=? AND status='active' ORDER BY date, time",
            (user_id, today),
        )
        return _rows_to_dicts(r)


def get_bookings_by_date(date: str):
    with _client() as c:
        r = c.execute("SELECT * FROM bookings WHERE date=? AND status='active' ORDER BY time", (date,))
        return _rows_to_dicts(r)


def get_upcoming_bookings(from_date: str):
    with _client() as c:
        r = c.execute(
            "SELECT * FROM bookings WHERE date>=? AND status='active' ORDER BY date, time",
            (from_date,),
        )
        return _rows_to_dicts(r)


def cancel_booking(booking_id: int):
    with _client() as c:
        c.execute("UPDATE bookings SET status='cancelled' WHERE id=?", (booking_id,))


def get_booking(booking_id: int):
    with _client() as c:
        r = c.execute("SELECT * FROM bookings WHERE id=?", (booking_id,))
        rows = _rows_to_dicts(r)
        return rows[0] if rows else None


def block_slot(date: str, time: str):
    with _client() as c:
        c.execute(
            "INSERT INTO blocked_slots (date, time) VALUES (?, ?) ON CONFLICT(date, time) DO NOTHING",
            (date, time),
        )


def unblock_slot(date: str, time: str):
    with _client() as c:
        c.execute("DELETE FROM blocked_slots WHERE date=? AND time=?", (date, time))


def get_blocked_slots(date: str = None):
    with _client() as c:
        if date:
            r = c.execute("SELECT * FROM blocked_slots WHERE date=? ORDER BY time", (date,))
        else:
            r = c.execute("SELECT * FROM blocked_slots ORDER BY date, time")
        return _rows_to_dicts(r)


def save_scheduled_post(text: str, photo: str, scheduled_at: str) -> int:
    with _client() as c:
        r = c.execute(
            "INSERT INTO scheduled_posts (text, photo, scheduled_at) VALUES (?,?,?)",
            (text, photo, scheduled_at),
        )
        return r.last_insert_rowid


def get_scheduled_posts():
    with _client() as c:
        r = c.execute("SELECT * FROM scheduled_posts WHERE status='pending' ORDER BY scheduled_at")
        return _rows_to_dicts(r)


def mark_post_sent(post_id: int):
    with _client() as c:
        c.execute("UPDATE scheduled_posts SET status='sent' WHERE id=?", (post_id,))


def save_broadcast_messages(sent_messages: list) -> int:
    with _client() as c:
        r = c.execute("INSERT INTO broadcasts (messages) VALUES (?)", (json.dumps(sent_messages),))
        return r.last_insert_rowid


def get_broadcast_messages(broadcast_id: int) -> list:
    with _client() as c:
        r = c.execute("SELECT messages FROM broadcasts WHERE id=?", (broadcast_id,))
        if not r.rows:
            return []
        return json.loads(r.rows[0][0])


def delete_broadcast_messages(broadcast_id: int):
    with _client() as c:
        c.execute("DELETE FROM broadcasts WHERE id=?", (broadcast_id,))
