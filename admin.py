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

# ───── UI ─────
def is_admin(update: Update):
    return update.effective_user and update.effective_user.id in ADMIN_IDS

def main_kb():
    return InlineKeyboardMarkup([
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

        if data == "m_clients":
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
