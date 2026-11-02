"""Standalone admin bot for @klientglowroom_bot. 
Receives booking notifications, lets admin view clients and broadcast posts.
Uses Neon Postgres database (same as main booking bot).
"""
import os
import logging
import traceback
import asyncio
import psycopg2
import psycopg2.extras
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from aiohttp import web
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes,
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

TOKEN       = os.getenv("TOKEN", "8647746412:AAFD1ZRI9jbzr5GdgTkGCKzTI15UX9OvPM0")
DATABASE_URL= os.getenv("DATABASE_URL", "postgresql://neondb_owner:npg_amcl2Yo7AduF@ep-dawn-glade-b4a7c7vq-pooler.c-6.us-east-2.aws.neon.tech/neondb?sslmode=require")
ADMIN_IDS   = [int(x) for x in os.getenv("ADMIN_IDS", "715653302,456903781").split(",") if x.strip()]
PORT        = int(os.getenv("PORT", "10000"))

# ───── Weekly schedule ─────
SCHEDULE_BY_WEEKDAY = {
    0: ["12:00", "13:00", "14:00", "15:00", "16:00", "17:00", "18:00"],
    1: ["12:00", "13:00", "14:00", "16:15", "17:00", "18:00"],
    2: ["13:30", "14:30", "15:30", "16:30", "17:30"],
    3: ["14:00", "15:00", "16:00", "18:30"],
    4: ["14:00", "15:00", "16:00", "17:00", "18:00"],
    5: ["10:00", "11:00", "12:00", "13:00", "14:00", "15:00", "17:00"],
    6: ["10:00", "11:00", "12:00", "13:00", "14:00"],
}
WEEKDAY_UA = {0:"Пн", 1:"Вт", 2:"Ср", 3:"Чт", 4:"Пт", 5:"Сб", 6:"Вс"}

# ───── DB helpers ─────
def _conn():
    return psycopg2.connect(DATABASE_URL)

def db_init():
    with _conn() as c, c.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS clients (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                first_name TEXT,
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
        """)
        c.commit()

def db_get_clients():
    with _conn() as c, c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM clients ORDER BY created_at DESC")
        return [dict(r) for r in cur.fetchall()]

def db_get_posts():
    with _conn() as c, c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM scheduled_posts WHERE status='pending' ORDER BY scheduled_at")
        return [dict(r) for r in cur.fetchall()]

def db_create_post(text, photo, scheduled_at):
    with _conn() as c, c.cursor() as cur:
        cur.execute("INSERT INTO scheduled_posts(text, photo, scheduled_at) VALUES (%s,%s,%s) RETURNING id",
                    (text, photo, scheduled_at))
        pid = cur.fetchone()[0]
        c.commit()
        return pid

def db_delete_post(post_id):
    with _conn() as c, c.cursor() as cur:
        cur.execute("DELETE FROM scheduled_posts WHERE id=%s", (post_id,))
        c.commit()


# ───── Booking management ─────
def db_get_upcoming_bookings():
    today = datetime.now().strftime("%Y-%m-%d")
    with _conn() as c, c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT * FROM bookings WHERE date>=%s AND status='active' ORDER BY date, time LIMIT 50",
            (today,)
        )
        return [dict(r) for r in cur.fetchall()]

def db_get_booking(booking_id):
    with _conn() as c, c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM bookings WHERE id=%s", (booking_id,))
        row = cur.fetchone()
        return dict(row) if row else None

def db_cancel_booking(booking_id):
    with _conn() as c, c.cursor() as cur:
        cur.execute("UPDATE bookings SET status='cancelled' WHERE id=%s", (booking_id,))
        c.commit()


# ───── Block/unblock slots ─────
def db_block_slot(date, time):
    with _conn() as c, c.cursor() as cur:
        cur.execute(
            "CREATE TABLE IF NOT EXISTS blocked_slots (id SERIAL PRIMARY KEY, date TEXT NOT NULL, time TEXT NOT NULL, created_at TIMESTAMP DEFAULT NOW(), UNIQUE(date, time))"
        )
        cur.execute(
            "INSERT INTO blocked_slots(date, time) VALUES (%s, %s) ON CONFLICT (date, time) DO NOTHING",
            (date, time)
        )
        c.commit()

def db_unblock_slot(date, time):
    with _conn() as c, c.cursor() as cur:
        cur.execute("DELETE FROM blocked_slots WHERE date=%s AND time=%s", (date, time))
        c.commit()

def db_get_blocked_slots_from(from_date):
    with _conn() as c, c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        try:
            cur.execute("SELECT * FROM blocked_slots WHERE date>=%s ORDER BY date, time", (from_date,))
            return [dict(r) for r in cur.fetchall()]
        except Exception:
            return []

def db_get_blocked_for_date(date):
    with _conn() as c, c.cursor() as cur:
        try:
            cur.execute("SELECT time FROM blocked_slots WHERE date=%s", (date,))
            return [r[0] for r in cur.fetchall()]
        except Exception:
            return []

def db_get_booked_times_adm(date):
    with _conn() as c, c.cursor() as cur:
        cur.execute("SELECT time FROM bookings WHERE date=%s AND status='active'", (date,))
        return [r[0] for r in cur.fetchall()]

# ───── UI ─────
def is_admin(update: Update):
    return update.effective_user and update.effective_user.id in ADMIN_IDS

def main_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Записи",             callback_data="m_bookings")],
        [InlineKeyboardButton("🔒 Заблокувати час",    callback_data="m_block")],
        [InlineKeyboardButton("🔓 Розблоковані слоти", callback_data="m_blocked")],
        [InlineKeyboardButton("📝 Створити пост",     callback_data="m_post")],
        [InlineKeyboardButton("📋 Заплановані пости", callback_data="m_sched")],
        [InlineKeyboardButton("👥 База клієнтів",     callback_data="m_clients")],
    ])

def back_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="m_back")]])


# ───── Handlers ─────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("/start user=%s is_admin=%s", update.effective_user.id, is_admin(update))
    if not is_admin(update):
        await update.message.reply_text("❌ Немає доступу.")
        return
    await update.message.reply_text(
        "👑 *GlowRoom Admin*\n\nОбери дію 👇",
        reply_markup=main_kb(),
        parse_mode="Markdown",
    )

async def menu_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    logger.info("menu_cb data=%s user=%s", q.data, update.effective_user.id)
    try:
        await q.answer()
    except Exception as e:
        logger.warning("answer failed: %s", e)
    if not is_admin(update):
        try:
            await q.edit_message_text("❌ Немає доступу.")
        except Exception:
            pass
        return

    try:
        data = q.data

        if data == "m_bookings":
            bookings = db_get_upcoming_bookings()
            if not bookings:
                await q.edit_message_text("📅 Активних записів немає.", reply_markup=back_kb())
                return
            lines = [f"📅 *Активних записів:* {len(bookings)}", ""]
            rows_bk = []
            for b in bookings[:30]:
                try:
                    d = datetime.strptime(b.get("date",""), "%Y-%m-%d").strftime("%d.%m")
                except Exception:
                    d = b.get("date","?")
                lines.append(f"• #{b['id']} · {d} {b.get('time','?')} · {b.get('name','?')} · {b.get('phone','?')}")
                rows_bk.append([InlineKeyboardButton(f"❌ Відмінити #{b['id']}", callback_data=f"b_cancel_{b['id']}")])
            rows_bk.append([InlineKeyboardButton("◀️ Назад", callback_data="m_back")])
            await q.edit_message_text("\n".join(lines), parse_mode="Markdown",
                                      reply_markup=InlineKeyboardMarkup(rows_bk))

        elif data.startswith("b_cancel_"):
            bid = int(data.replace("b_cancel_", ""))
            booking = db_get_booking(bid)
            if not booking:
                await q.edit_message_text("Запис не знайдено.", reply_markup=back_kb())
                return
            try:
                d = datetime.strptime(booking.get("date",""), "%Y-%m-%d").strftime("%d.%m")
            except Exception:
                d = booking.get("date","?")
            rows_cf = [
                [InlineKeyboardButton("✅ Так, відмінити", callback_data=f"b_confirm_{bid}")],
                [InlineKeyboardButton("↩️ Ні, залишити",   callback_data="m_bookings")],
            ]
            await q.edit_message_text(
                f"❗️ Відмінити запис #{bid} · {d} {booking.get('time','?')} · {booking.get('name','?')}?",
                reply_markup=InlineKeyboardMarkup(rows_cf)
            )

        elif data.startswith("b_confirm_"):
            bid = int(data.replace("b_confirm_", ""))
            if db_get_booking(bid):
                db_cancel_booking(bid)
                await q.edit_message_text(f"✅ Запис #{bid} відмінено.", reply_markup=back_kb())
            else:
                await q.edit_message_text("Запис не знайдено.", reply_markup=back_kb())

        elif data == "m_block":
            today_ = datetime.now()
            rows_bl = []
            for i in range(14):
                dd = today_ + timedelta(days=i)
                wd = WEEKDAY_UA.get(dd.weekday(), "")
                label = f"{dd.strftime('%d.%m')} ({wd})" + (" — сьогодні" if i == 0 else "")
                rows_bl.append([InlineKeyboardButton(label, callback_data=f"blk_d_{dd.strftime('%Y-%m-%d')}")])
            rows_bl.append([InlineKeyboardButton("◀️ Назад", callback_data="m_back")])
            await q.edit_message_text("📅 Оберіть дату щоб заблокувати слот:",
                                      reply_markup=InlineKeyboardMarkup(rows_bl))

        elif data.startswith("blk_d_"):
            date_str = data.replace("blk_d_", "")
            try:
                dt_ = datetime.strptime(date_str, "%Y-%m-%d")
            except ValueError:
                await q.edit_message_text("Невірна дата.", reply_markup=back_kb())
                return
            slots_bl = SCHEDULE_BY_WEEKDAY.get(dt_.weekday(), [])
            booked_set = set(db_get_booked_times_adm(date_str))
            blocked_set = set(db_get_blocked_for_date(date_str))
            rows_slot = []
            row_ = []
            for t in slots_bl:
                tag = ""
                cb = f"blk_t_{date_str}_{t}"
                if t in blocked_set:
                    tag = "🔒"; cb = f"blk_u_{date_str}_{t}"
                elif t in booked_set:
                    tag = "📌"
                row_.append(InlineKeyboardButton(f"{tag}{t}", callback_data=cb))
                if len(row_) == 3:
                    rows_slot.append(row_); row_ = []
            if row_: rows_slot.append(row_)
            rows_slot.append([InlineKeyboardButton("◀️ Назад", callback_data="m_block")])
            await q.edit_message_text(
                f"🕐 Слоти на {dt_.strftime('%d.%m.%Y')}\n\n📌 — вже є запис\n🔒 — заблоковано (натисни щоб розблокувати)\nІнші — натисни щоб заблокувати",
                reply_markup=InlineKeyboardMarkup(rows_slot)
            )

        elif data.startswith("blk_t_"):
            parts_ = data.replace("blk_t_", "").split("_", 1)
            if len(parts_) == 2:
                db_block_slot(parts_[0], parts_[1])
                q.data = f"blk_d_{parts_[0]}"
                await menu_cb(update, context)
                return

        elif data.startswith("blk_u_"):
            parts_ = data.replace("blk_u_", "").split("_", 1)
            if len(parts_) == 2:
                db_unblock_slot(parts_[0], parts_[1])
                q.data = f"blk_d_{parts_[0]}"
                await menu_cb(update, context)
                return

        elif data == "m_blocked":
            today_s = datetime.now().strftime("%Y-%m-%d")
            blocked_list = db_get_blocked_slots_from(today_s)
            if not blocked_list:
                await q.edit_message_text("🔓 Заблокованих слотів немає.", reply_markup=back_kb())
                return
            lines_bl = [f"🔒 *Заблоковано:* {len(blocked_list)}", ""]
            rows_bl2 = []
            for bb in blocked_list[:30]:
                try:
                    d = datetime.strptime(bb["date"], "%Y-%m-%d").strftime("%d.%m")
                except Exception:
                    d = bb["date"]
                lines_bl.append(f"• {d} {bb['time']}")
                rows_bl2.append([InlineKeyboardButton(
                    f"🔓 Розблокувати {d} {bb['time']}",
                    callback_data=f"blk_u_{bb['date']}_{bb['time']}"
                )])
            rows_bl2.append([InlineKeyboardButton("◀️ Назад", callback_data="m_back")])
            await q.edit_message_text("\n".join(lines_bl), parse_mode="Markdown",
                                      reply_markup=InlineKeyboardMarkup(rows_bl2))

        elif data == "m_clients":
            clients = db_get_clients()
            if not clients:
                text = "👥 База порожня."
            else:
                lines = [f"👥 *База клієнтів:* {len(clients)}", ""]
                for c in clients[:50]:
                    uname = c.get("username") or "—"
                    fname = c.get("first_name") or "—"
                    lines.append(f"• {fname} @{uname}")
                if len(clients) > 50:
                    lines.append(f"\n_...і ще {len(clients)-50}_")
                text = "\n".join(lines)
            await q.edit_message_text(text, parse_mode="Markdown", reply_markup=back_kb())

        elif data == "m_sched":
            posts = db_get_posts()
            if not posts:
                await q.edit_message_text("📋 Запланованих постів немає.", reply_markup=back_kb())
                return
            lines = [f"📋 *Заплановані:* {len(posts)}", ""]
            rows = []
            for p in posts:
                prev = (p.get("text") or "")[:60]
                lines.append(f"• #{p['id']} — {p.get('scheduled_at','?')}\n  _{prev}_")
                rows.append([InlineKeyboardButton(f"🗑️ #{p['id']}", callback_data=f"del_{p['id']}")])
            rows.append([InlineKeyboardButton("◀️ Назад", callback_data="m_back")])
            await q.edit_message_text("\n".join(lines), parse_mode="Markdown",
                                      reply_markup=InlineKeyboardMarkup(rows))

        elif data == "m_post":
            context.user_data.clear()
            context.user_data["st"] = "wait_text"
            await q.edit_message_text("✏️ Надішли *текст* поста:", parse_mode="Markdown")

        elif data == "m_back":
            context.user_data.clear()
            await q.edit_message_text("👑 *GlowRoom Admin*\n\nОбери дію 👇",
                                      parse_mode="Markdown", reply_markup=main_kb())

        elif data.startswith("del_"):
            pid = int(data.replace("del_", ""))
            db_delete_post(pid)
            await q.edit_message_text(f"✅ Пост #{pid} видалено.", reply_markup=back_kb())

        elif data == "p_nophoto":
            context.user_data["photo"] = None
            await _ask_schedule(q, context)

        elif data == "p_now":
            await _do_send(update, context, now=True, q=q)

        elif data == "p_later":
            today = datetime.now()
            rows = []
            for i in range(7):
                d = today + timedelta(days=i)
                rows.append([InlineKeyboardButton(d.strftime("%d.%m (%a)"),
                                                  callback_data=f"pd_{d.strftime('%Y-%m-%d')}")])
            rows.append([InlineKeyboardButton("◀️ Назад", callback_data="m_back")])
            await q.edit_message_text("📅 Оберіть дату:", reply_markup=InlineKeyboardMarkup(rows))

        elif data.startswith("pd_"):
            date = data.replace("pd_", "")
            context.user_data["date"] = date
            rows = [[InlineKeyboardButton(f"{h:02d}:00", callback_data=f"pt_{h:02d}:00")]
                    for h in range(9, 22)]
            await q.edit_message_text(f"🕐 Час для {date}:", reply_markup=InlineKeyboardMarkup(rows))

        elif data.startswith("pt_"):
            tm = data.replace("pt_", "")
            context.user_data["time"] = tm
            await _show_confirm(update, context, now=False, q=q)

        elif data == "p_confirm_now":
            await _do_send(update, context, now=True, q=q)

        elif data == "p_confirm_later":
            await _do_send(update, context, now=False, q=q)

        elif data == "p_cancel":
            context.user_data.clear()
            await q.edit_message_text("❌ Скасовано.", reply_markup=back_kb())

        else:
            logger.warning("unknown callback data=%s", data)

    except Exception as e:
        logger.error("menu_cb ERROR data=%s: %s\n%s", q.data, e, traceback.format_exc())
        try:
            await q.edit_message_text(f"❌ Помилка: `{type(e).__name__}: {str(e)[:200]}`",
                                      parse_mode="Markdown", reply_markup=back_kb())
        except Exception:
            pass


async def msg_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text / photo during post creation flow."""
    if not is_admin(update):
        return
    st = context.user_data.get("st")
    if not st:
        return
    try:
        if st == "wait_text" and update.message.text:
            context.user_data["text"] = update.message.text
            context.user_data["st"] = "wait_photo"
            await update.message.reply_text(
                "📸 Прикріпи фото або натисни кнопку:",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("➡️ Без фото", callback_data="p_nophoto")]]
                ),
            )
        elif st == "wait_photo" and update.message.photo:
            context.user_data["photo"] = update.message.photo[-1].file_id
            await _ask_schedule(update.message, context)
    except Exception as e:
        logger.exception("msg_handler failed")
        await update.message.reply_text(f"❌ Помилка: {e}")


async def _ask_schedule(target, context):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Надіслати зараз", callback_data="p_now")],
        [InlineKeyboardButton("⏰ Запланувати",     callback_data="p_later")],
        [InlineKeyboardButton("❌ Скасувати",        callback_data="p_cancel")],
    ])
    text = "⏱️ Коли надіслати?"
    if hasattr(target, "edit_message_text"):
        await target.edit_message_text(text, reply_markup=kb)
    else:
        await target.reply_text(text, reply_markup=kb)
    context.user_data["st"] = "wait_schedule"


async def _show_confirm(update, context, now, q):
    text = context.user_data.get("text", "")
    label = "зараз" if now else f"{context.user_data.get('date')} {context.user_data.get('time')}"
    preview = f"📬 *Підтвердження*\n\n{text}\n\n⏰ _{label}_"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(("✅ Надіслати" if now else "✅ Запланувати"),
                              callback_data=("p_confirm_now" if now else "p_confirm_later"))],
        [InlineKeyboardButton("❌ Скасувати", callback_data="p_cancel")],
    ])
    await q.edit_message_text(preview, parse_mode="Markdown", reply_markup=kb)


async def _do_send(update, context, now, q):
    text  = context.user_data.get("text", "")
    photo = context.user_data.get("photo")
    if now:
        try:
            count = await _broadcast(context.bot, text, photo)
            await q.edit_message_text(f"✅ Надіслано {count} клієнтам.", reply_markup=back_kb())
        except Exception as e:
            logger.exception("broadcast now failed")
            await q.edit_message_text(f"❌ Помилка: {e}", reply_markup=back_kb())
    else:
        date = context.user_data.get("date")
        time_s = context.user_data.get("time")
        when = f"{date} {time_s}"
        try:
            pid = db_create_post(text, photo, when)
            await q.edit_message_text(f"✅ Заплановано на {when} (#{pid})", reply_markup=back_kb())
        except Exception as e:
            logger.exception("create_post failed")
            await q.edit_message_text(f"❌ Помилка: {e}", reply_markup=back_kb())
    context.user_data.clear()


async def _broadcast(bot, text, photo):
    clients = db_get_clients()
    sent = 0
    for c in clients:
        uid = c.get("user_id")
        if not uid:
            continue
        try:
            if photo:
                await bot.send_photo(uid, photo, caption=text, parse_mode="Markdown")
            else:
                await bot.send_message(uid, text, parse_mode="Markdown")
            sent += 1
        except Exception as e:
            logger.warning("broadcast fail user=%s: %s", uid, e)
    return sent


async def err_handler(update, context):
    logger.error("GLOBAL_ERR: %s\n%s", context.error, "".join(traceback.format_exception(type(context.error), context.error, context.error.__traceback__)))


async def scheduler_loop(app):
    while True:
        try:
            posts = db_get_posts()
            now = datetime.now()
            for p in posts:
                try:
                    due = datetime.strptime(p["scheduled_at"], "%Y-%m-%d %H:%M")
                    if due <= now:
                        logger.info("Sending scheduled post #%s", p["id"])
                        await _broadcast(app.bot, p.get("text") or "", p.get("photo"))
                        db_delete_post(p["id"])
                except Exception:
                    logger.exception("Failed to process post %s", p.get("id"))
        except Exception:
            logger.exception("scheduler_loop iteration failed")
        await asyncio.sleep(60)


async def main():
    db_init()
    async def _health(req): return web.Response(text="ok")
    _web = web.Application()
    _web.router.add_get("/", _health)
    _web.router.add_get("/health", _health)
    _runner = web.AppRunner(_web)
    await _runner.setup()
    await web.TCPSite(_runner, "0.0.0.0", PORT).start()
    logger.info("Health server on %d", PORT)
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(menu_cb))
    app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO, msg_handler))
    app.add_error_handler(err_handler)
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    asyncio.create_task(scheduler_loop(app))
    logger.info("✅ Admin bot started (@klientglowroom_bot)")
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
