import os
import json
import psycopg2
import psycopg2.extras
from datetime import datetime

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:PLACEHOLDER@db.sfqezgzmnoivsucxyckm.supabase.co:5432/postgres")


def get_conn():
    conn = psycopg2.connect(DATABASE_URL)
    return conn


def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS clients (
            user_id BIGINT PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS bookings (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            service_id TEXT,
            date TEXT,
            time TEXT,
            name TEXT,
            phone TEXT,
            status TEXT DEFAULT 'active',
            created_at TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS scheduled_posts (
            id SERIAL PRIMARY KEY,
            text TEXT,
            photo TEXT,
            scheduled_at TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS broadcasts (
            id SERIAL PRIMARY KEY,
            messages TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)
    conn.commit()
    cur.close()
    conn.close()


def add_client(user_id: int, username: str, first_name: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO clients (user_id, username, first_name) VALUES (%s, %s, %s) ON CONFLICT (user_id) DO NOTHING",
        (user_id, username, first_name)
    )
    conn.commit()
    cur.close()
    conn.close()


def get_all_clients():
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM clients")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [dict(r) for r in rows]


def create_booking(user_id, service_id, date, time, name, phone):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO bookings (user_id, service_id, date, time, name, phone) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
        (user_id, service_id, date, time, name, phone)
    )
    booking_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return booking_id


def get_booked_times(date: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT time FROM bookings WHERE date=%s AND status='active'", (date,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [r[0] for r in rows]


def get_client_bookings(user_id: int):
    today = datetime.now().strftime("%Y-%m-%d")
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        "SELECT * FROM bookings WHERE user_id=%s AND date>=%s AND status='active' ORDER BY date, time",
        (user_id, today)
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [dict(r) for r in rows]


def get_bookings_by_date(date: str):
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM bookings WHERE date=%s AND status='active' ORDER BY time", (date,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [dict(r) for r in rows]


def get_upcoming_bookings(from_date: str):
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        "SELECT * FROM bookings WHERE date>=%s AND status='active' ORDER BY date, time",
        (from_date,)
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [dict(r) for r in rows]


def save_scheduled_post(text: str, photo: str, scheduled_at: str) -> int:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO scheduled_posts (text, photo, scheduled_at) VALUES (%s, %s, %s) RETURNING id",
        (text, photo, scheduled_at)
    )
    post_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return post_id


def get_scheduled_posts():
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM scheduled_posts WHERE status='pending' ORDER BY scheduled_at")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [dict(r) for r in rows]


def mark_post_sent(post_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE scheduled_posts SET status='sent' WHERE id=%s", (post_id,))
    conn.commit()
    cur.close()
    conn.close()


def save_broadcast_messages(sent_messages: list) -> int:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO broadcasts (messages) VALUES (%s) RETURNING id",
        (json.dumps(sent_messages),)
    )
    broadcast_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return broadcast_id


def get_broadcast_messages(broadcast_id: int) -> list:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT messages FROM broadcasts WHERE id=%s", (broadcast_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return []
    return json.loads(row[0])


def delete_broadcast_messages(broadcast_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM broadcasts WHERE id=%s", (broadcast_id,))
    conn.commit()
    cur.close()
    conn.close()
