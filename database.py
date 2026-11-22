"""Turso-backed DB via HTTP (hrana v2 pipeline). No websocket, no deps."""
import os
import json
import urllib.request
from datetime import datetime

TURSO_URL = os.getenv("TURSO_DATABASE_URL", "").replace("libsql://", "https://").rstrip("/")
TURSO_TOKEN = os.getenv("TURSO_AUTH_TOKEN", "")


def _py_to_arg(v):
    if v is None:
        return {"type": "null", "value": None}
    if isinstance(v, bool):
        return {"type": "integer", "value": str(int(v))}
    if isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        return {"type": "float", "value": v}
    if isinstance(v, (bytes, bytearray)):
        import base64
        return {"type": "blob", "base64": base64.b64encode(v).decode()}
    return {"type": "text", "value": str(v)}


def _arg_to_py(a):
    t = a.get("type")
    v = a.get("value")
    if t == "null":
        return None
    if t == "integer":
        return int(v)
    if t == "float":
        return float(v)
    if t == "blob":
        import base64
        return base64.b64decode(a.get("base64", ""))
    return v  # text


def _execute(sql, params=()):
    body = {
        "requests": [
            {"type": "execute", "stmt": {"sql": sql, "args": [_py_to_arg(p) for p in params]}},
            {"type": "close"},
        ]
    }
    req = urllib.request.Request(
        f"{TURSO_URL}/v2/pipeline",
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {TURSO_TOKEN}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    r = data["results"][0]
    if r.get("type") == "error":
        raise RuntimeError(f"Turso error: {r.get('error',{}).get('message','?')}")
    return r["response"]["result"]


def _batch(statements):
    reqs = [{"type": "execute", "stmt": {"sql": s, "args": []}} for s in statements]
    reqs.append({"type": "close"})
    body = {"requests": reqs}
    req = urllib.request.Request(
        f"{TURSO_URL}/v2/pipeline",
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {TURSO_TOKEN}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def _rows_to_dicts(result):
    cols = [c["name"] for c in result.get("cols", [])]
    return [dict(zip(cols, [_arg_to_py(v) for v in row])) for row in result.get("rows", [])]


def _rows_raw(result):
    return [[_arg_to_py(v) for v in row] for row in result.get("rows", [])]


def init_db():
    _batch([
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


def add_client(user_id, username, first_name):
    _execute(
        "INSERT INTO clients (user_id, username, first_name) VALUES (?, ?, ?) ON CONFLICT(user_id) DO NOTHING",
        (user_id, username, first_name),
    )


def get_all_clients():
    return _rows_to_dicts(_execute("SELECT * FROM clients"))


def create_booking(user_id, service_id, date, time, name, phone):
    r = _execute(
        "INSERT INTO bookings (user_id, service_id, date, time, name, phone) VALUES (?,?,?,?,?,?)",
        (user_id, service_id, date, time, name, phone),
    )
    lid = r.get("last_insert_rowid")
    return int(lid) if lid is not None else None


def get_booked_times(date):
    r = _execute("SELECT time FROM bookings WHERE date=? AND status='active'", (date,))
    booked = [row[0] for row in _rows_raw(r)]
    r2 = _execute("SELECT time FROM blocked_slots WHERE date=?", (date,))
    blocked = [row[0] for row in _rows_raw(r2)]
    return list(set(booked + blocked))


def get_client_bookings(user_id):
    today = datetime.now().strftime("%Y-%m-%d")
    return _rows_to_dicts(_execute(
        "SELECT * FROM bookings WHERE user_id=? AND date>=? AND status='active' ORDER BY date, time",
        (user_id, today),
    ))


def get_bookings_by_date(date):
    return _rows_to_dicts(_execute(
        "SELECT * FROM bookings WHERE date=? AND status='active' ORDER BY time", (date,)
    ))


def get_upcoming_bookings(from_date):
    return _rows_to_dicts(_execute(
        "SELECT * FROM bookings WHERE date>=? AND status='active' ORDER BY date, time", (from_date,)
    ))


def cancel_booking(booking_id):
    _execute("UPDATE bookings SET status='cancelled' WHERE id=?", (booking_id,))


def get_booking(booking_id):
    rows = _rows_to_dicts(_execute("SELECT * FROM bookings WHERE id=?", (booking_id,)))
    return rows[0] if rows else None


def block_slot(date, time):
    _execute(
        "INSERT INTO blocked_slots (date, time) VALUES (?, ?) ON CONFLICT(date, time) DO NOTHING",
        (date, time),
    )


def unblock_slot(date, time):
    _execute("DELETE FROM blocked_slots WHERE date=? AND time=?", (date, time))


def get_blocked_slots(date=None):
    if date:
        return _rows_to_dicts(_execute(
            "SELECT * FROM blocked_slots WHERE date=? ORDER BY time", (date,)
        ))
    return _rows_to_dicts(_execute("SELECT * FROM blocked_slots ORDER BY date, time"))


def save_scheduled_post(text, photo, scheduled_at):
    r = _execute(
        "INSERT INTO scheduled_posts (text, photo, scheduled_at) VALUES (?,?,?)",
        (text, photo, scheduled_at),
    )
    lid = r.get("last_insert_rowid")
    return int(lid) if lid is not None else None


def get_scheduled_posts():
    return _rows_to_dicts(_execute(
        "SELECT * FROM scheduled_posts WHERE status='pending' ORDER BY scheduled_at"
    ))


def mark_post_sent(post_id):
    _execute("UPDATE scheduled_posts SET status='sent' WHERE id=?", (post_id,))


def save_broadcast_messages(sent_messages):
    r = _execute("INSERT INTO broadcasts (messages) VALUES (?)", (json.dumps(sent_messages),))
    lid = r.get("last_insert_rowid")
    return int(lid) if lid is not None else None


def get_broadcast_messages(broadcast_id):
    r = _execute("SELECT messages FROM broadcasts WHERE id=?", (broadcast_id,))
    rows = _rows_raw(r)
    if not rows:
        return []
    return json.loads(rows[0][0])


def delete_broadcast_messages(broadcast_id):
    _execute("DELETE FROM broadcasts WHERE id=?", (broadcast_id,))


# Compat shim for admin.py which imports _client as a context manager
class _ClientCtx:
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def execute(self, sql, params=()):
        return _execute(sql, params)


def _client():
    return _ClientCtx()
