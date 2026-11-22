"""Standalone admin bot for @klientglowroom_bot.
Full features: view bookings with cancel, block/unblock time slots,
broadcast posts, client base. Uses Turso (libSQL) DB.
"""
import os
import logging
import traceback
import asyncio
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from aiohttp import web
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes,
)

# Shared DB layer (Turso/libSQL via HTTP)
from database import (
    init_db as db_init,
    get_all_clients as db_get_clients,
    get_scheduled_posts as db_get_posts,
    save_scheduled_post as db_create_post,
    get_upcoming_bookings,
    get_booking,
    cancel_booking as db_cancel_booking,
    block_slot as db_block_slot,
    unblock_slot as db_unblock_slot,
    get_blocked_slots as db_get_blocked_slots,
    _client as _db_client,
)


def db_delete_post(post_id):
    with _db_client() as c:
        c.execute("DELETE FROM scheduled_posts WHERE id=?", (post_id,))


logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

TOKEN     = os.getenv("TOKEN", "8647746412:AAFD1ZRI9jbzr5GdgTkGCKzTI15UX9OvPM0")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "715653302,456903781").split(",") if x.strip()]
PORT      = int(os.getenv("PORT", "10000"))

WEEKDAY_UA = ["Понеділок","Вівторок","Середа","Четвер","П'ятниця","Субота","Неділя"]

# Schedule by weekday (same as bot.py)
SCHEDULE_BY_WEEKDAY = {
    0: ["12:00","13:00","14:00","15:00","16:00","17:00","18:00"],              # Пн
    1: ["12:00","13:00","16:15","17:00","18:00"],                              # Вт
    2: ["13:30","14:30","15:30","16:30","17:30","18:00"],                      # Ср
    3: ["14:00","15:00","16:00","18:30"],                                      # Чт
    4: ["14:00","15:00","16:00","17:00","18:00"],                              # Пт
    5: ["10:00","11:00","12:00","13:00","14:00","15:00","17:00"],              # Сб
    6: ["10:00","11:00","12:00","13:00","14:00"],                              # Нд
}


def fmt_date(ymd):
    try:
        dt = datetime.strptime(ymd, "%Y-%m-%d")
        return f"{dt.strftime('%d.%m.%Y')} ({WEEKDAY_UA[dt.weekday()]})"
    except Exception:
        return ymd


# ───── UI ─────
def is_admin(update: Update):
    return update.effective_user and update.effective_user.id in ADMIN_IDS


def main_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Записи",              callback_data="m_bookings")],
        [InlineKeyboardButton("🔒 Заблокувати час",     callback_data="m_block")],
        [InlineKeyboardButton("🔓 Розблоковані слоти",  callback_data="m_blocked")],
        [InlineKeyboardButton("📝 Створити пост",       callback_data="m_post")],
        [InlineKeyboardButton("📋 Заплановані пости",   callback_data="m_sched")],
        [InlineKeyboardButton("👥 База клієнтів",       callback_data="m_clients")],
    ])


def back_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="m_back")]])


# ───── Handlers ─────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    try:
        await q.answer()
    except Exception:
        pass
    if not is_admin(update):
        try: await q.edit_message_text("❌ Немає доступу.")
        except: pass
        return

    data = q.data
    try:
        # ── MAIN MENU ──
        if data == "m_back":
            context.user_data.clear()
            await q.edit_message_text("👑 *GlowRoom Admin*\n\nОбери дію 👇",
                                      parse_mode="Markdown", reply_markup=main_kb())
            return

        # ── BOOKINGS ──
        if data == "m_bookings":
            today = datetime.now().strftime("%Y-%m-%d")
            bookings = get_upcoming_bookings(today)
            if not bookings:
                await q.edit_message_text("📅 Активних записів немає.", reply_markup=back_kb())
                return
            lines = [f"📅 *Активні записи:* {len(bookings)}", ""]
            rows = []
            for b in bookings[:30]:
                lines.append(f"• #{b['id']} — {fmt_date(b['date'])} {b['time']}\n  {b.get('name','?')} {b.get('phone','')}")
                rows.append([InlineKeyboardButton(f"❌ Скасувати #{b['id']} ({b['date']} {b['time']})",
                                                  callback_data=f"b_cancel_{b['id']}")])
            if len(bookings) > 30:
                lines.append(f"\n_...і ще {len(bookings)-30}_")
            rows.append([InlineKeyboardButton("◀️ Назад", callback_data="m_back")])
            await q.edit_message_text("\n".join(lines), parse_mode="Markdown",
                                      reply_markup=InlineKeyboardMarkup(rows))
            return

        if data.startswith("b_cancel_"):
            bid = int(data.replace("b_cancel_", ""))
            b = get_booking(bid)
            if not b:
                await q.edit_message_text("❌ Запис не знайдено.", reply_markup=back_kb())
                return
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Так, скасувати", callback_data=f"b_confirm_{bid}")],
                [InlineKeyboardButton("◀️ Відмінити",      callback_data="m_bookings")],
            ])
            await q.edit_message_text(
                f"Скасувати запис?\n\n#{bid} — {fmt_date(b['date'])} {b['time']}\n{b.get('name','')} {b.get('phone','')}",
                reply_markup=kb,
            )
            return

        if data.startswith("b_confirm_"):
            bid = int(data.replace("b_confirm_", ""))
            db_cancel_booking(bid)
            await q.edit_message_text(f"✅ Запис #{bid} скасовано.", reply_markup=back_kb())
            return

        # ── BLOCK SLOT ──
        if data == "m_block":
            rows = []
            for i in range(14):
                d = datetime.now() + timedelta(days=i)
                rows.append([InlineKeyboardButton(
                    d.strftime('%d.%m') + f" ({WEEKDAY_UA[d.weekday()][:2]})",
                    callback_data=f"blk_d_{d.strftime('%Y-%m-%d')}")])
            rows.append([InlineKeyboardButton("◀️ Назад", callback_data="m_back")])
            await q.edit_message_text("🔒 *Заблокувати час*\n\nОбери дату:",
                                      parse_mode="Markdown",
                                      reply_markup=InlineKeyboardMarkup(rows))
            return

        if data.startswith("blk_d_"):
            date = data.replace("blk_d_", "")
            try:
                wd = datetime.strptime(date, "%Y-%m-%d").weekday()
            except:
                wd = 0
            slots = SCHEDULE_BY_WEEKDAY.get(wd, [])
            blocked_now = {b['time'] for b in db_get_blocked_slots(date)}
            rows = []
            row = []
            for t in slots:
                mark = " 🔒" if t in blocked_now else ""
                row.append(InlineKeyboardButton(f"{t}{mark}", callback_data=f"blk_t_{date}_{t}"))
                if len(row) == 3:
                    rows.append(row); row = []
            if row: rows.append(row)
            rows.append([InlineKeyboardButton("◀️ Назад", callback_data="m_block")])
            await q.edit_message_text(f"🔒 *{fmt_date(date)}*\n\nОбери час для блокування:",
                                      parse_mode="Markdown",
                                      reply_markup=InlineKeyboardMarkup(rows))
            return

        if data.startswith("blk_t_"):
            _, _, date, time = data.split("_", 3)
            db_block_slot(date, time)
            await q.edit_message_text(
                f"🔒 Час {time} на {fmt_date(date)} заблоковано.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔒 Ще заблокувати на цю дату", callback_data=f"blk_d_{date}")],
                    [InlineKeyboardButton("◀️ Меню",                       callback_data="m_back")],
                ]))
            return

        # ── BLOCKED SLOTS LIST ──
        if data == "m_blocked":
            all_blocked = db_get_blocked_slots()
            if not all_blocked:
                await q.edit_message_text("🔓 Заблокованих слотів немає.", reply_markup=back_kb())
                return
            lines = [f"🔓 *Заблоковані слоти:* {len(all_blocked)}", ""]
            rows = []
            for s in all_blocked[:30]:
                lines.append(f"• {fmt_date(s['date'])} — {s['time']}")
                rows.append([InlineKeyboardButton(f"🔓 Розблокувати {s['date']} {s['time']}",
                                                  callback_data=f"blk_u_{s['date']}_{s['time']}")])
            rows.append([InlineKeyboardButton("◀️ Назад", callback_data="m_back")])
            await q.edit_message_text("\n".join(lines), parse_mode="Markdown",
                                      reply_markup=InlineKeyboardMarkup(rows))
            return

        if data.startswith("blk_u_"):
            _, _, date, time = data.split("_", 3)
            db_unblock_slot(date, time)
            await q.edit_message_text(f"🔓 {date} {time} розблоковано.", reply_markup=back_kb())
            return

        # ── CLIENTS ──
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
            return

        # ── SCHEDULED POSTS ──
        if data == "m_sched":
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
            return

        if data.startswith("del_"):
            pid = int(data.replace("del_", ""))
            db_delete_post(pid)
            await q.edit_message_text(f"✅ Пост #{pid} видалено.", reply_markup=back_kb())
            return

        # ── POST CREATION FLOW ──
        if data == "m_post":
            context.user_data.clear()
            context.user_data["st"] = "wait_text"
            await q.edit_message_text("✏️ Надішли *текст* поста:", parse_mode="Markdown")
            return

        if data == "p_nophoto":
            context.user_data["photo"] = None
            await _ask_schedule(q, context); return

        if data == "p_now":
            await _do_send(update, context, now=True, q=q); return

        if data == "p_later":
            rows = []
            for i in range(7):
                d = datetime.now() + timedelta(days=i)
                rows.append([InlineKeyboardButton(d.strftime("%d.%m (%a)"),
                                                  callback_data=f"pd_{d.strftime('%Y-%m-%d')}")])
            rows.append([InlineKeyboardButton("◀️ Назад", callback_data="m_back")])
            await q.edit_message_text("📅 Оберіть дату:", reply_markup=InlineKeyboardMarkup(rows))
            return

        if data.startswith("pd_"):
            date = data.replace("pd_", "")
            context.user_data["date"] = date
            rows = [[InlineKeyboardButton(f"{h:02d}:00", callback_data=f"pt_{h:02d}:00")]
                    for h in range(9, 22)]
            await q.edit_message_text(f"🕐 Час для {date}:", reply_markup=InlineKeyboardMarkup(rows))
            return

        if data.startswith("pt_"):
            tm = data.replace("pt_", "")
            context.user_data["time"] = tm
            await _show_confirm(update, context, now=False, q=q); return

        if data == "p_confirm_now":
            await _do_send(update, context, now=True, q=q); return

        if data == "p_confirm_later":
            await _do_send(update, context, now=False, q=q); return

        if data == "p_cancel":
            context.user_data.clear()
            await q.edit_message_text("❌ Скасовано.", reply_markup=back_kb()); return

        logger.warning("unknown callback data=%s", data)

    except Exception as e:
        logger.error("menu_cb ERROR data=%s: %s\n%s", q.data, e, traceback.format_exc())
        try:
            await q.edit_message_text(f"❌ Помилка: `{type(e).__name__}: {str(e)[:200]}`",
                                      parse_mode="Markdown", reply_markup=back_kb())
        except Exception:
            pass


async def msg_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    st = context.user_data.get("st")
    if not st: return
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
        if not uid: continue
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
    logger.error("GLOBAL_ERR: %s", context.error)


async def scheduler_loop(app):
    while True:
        try:
            posts = db_get_posts()
            now = datetime.now()
            for p in posts:
                try:
                    due = datetime.strptime(p["scheduled_at"], "%Y-%m-%d %H:%M")
                    if due <= now:
                        await _broadcast(app.bot, p.get("text") or "", p.get("photo"))
                        db_delete_post(p["id"])
                except Exception:
                    logger.exception("post %s failed", p.get("id"))
        except Exception:
            logger.exception("scheduler loop failed")
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
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(menu_cb))
    app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO, msg_handler))
    app.add_error_handler(err_handler)
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    asyncio.create_task(scheduler_loop(app))
    logger.info("✅ Admin bot started")
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
