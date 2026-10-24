import os
import logging
import traceback
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import database as db

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

NOTIFY_TOKEN = os.getenv("NOTIFY_TOKEN", "8647746412:AAFD1ZRI9jbzr5GdgTkGCKzTI15UX9OvPM0")
MAIN_BOT_TOKEN = os.getenv("BOT_TOKEN", "8664438342:AAF1i1tHXRZXMsqMrPwXGtQsrjL1ZreEmuA")
ADMIN_IDS = [715653302, 456903781]

POST_TEXT, POST_PHOTO, POST_SCHEDULE_TYPE, POST_SCHEDULE_DATE, POST_SCHEDULE_TIME, POST_CONFIRM = range(6)

scheduler = None  # set from run.py


# ═══════════════════════════════════════
#  UTILS
# ═══════════════════════════════════════

def is_admin(update: Update):
    return update.effective_user.id in ADMIN_IDS


def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Створити пост", callback_data="menu_create_post")],
        [InlineKeyboardButton("📋 Заплановані пости", callback_data="menu_scheduled")],
        [InlineKeyboardButton("👥 База клієнтів", callback_data="menu_clients")],
    ])


# ═══════════════════════════════════════
#  START
# ═══════════════════════════════════════

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("[NB] /start user=%s", update.effective_user.id)
    if not is_admin(update):
        await update.message.reply_text("❌ Немає доступу.")
        return
    await update.message.reply_text(
        "👑 *GlowRoom Admin*\n\nОбери дію 👇",
        reply_markup=main_keyboard(),
        parse_mode="Markdown",
    )


# ═══════════════════════════════════════
#  MENU
# ═══════════════════════════════════════

async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    logger.info("[NB] menu data=%s user=%s", q.data, update.effective_user.id)
    try:
        await q.answer()
    except Exception as e:
        logger.warning("[NB] answer failed: %s", e)

    if not is_admin(update):
        try:
            await q.edit_message_text("❌ Немає доступу.")
        except Exception:
            pass
        return

    try:
        if q.data == "menu_clients":
            clients = db.get_all_clients()
            if not clients:
                text = "👥 База клієнтів порожня."
            else:
                lines = [f"👥 *База клієнтів:* {len(clients)}", ""]
                for c in clients[:30]:
                    username = c.get("username") or "—"
                    first_name = c.get("first_name") or "Без імені"
                    lines.append(f"• {first_name} @{username}")
                if len(clients) > 30:
                    lines.append(f"\n_...і ще {len(clients) - 30}_")
                text = "\n".join(lines)

            await q.edit_message_text(
                text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("◀️ Назад", callback_data="menu_back")]]
                ),
            )

        elif q.data == "menu_scheduled":
            posts = db.get_scheduled_posts()
            if not posts:
                text = "📋 Запланованих постів немає."
            else:
                lines = [f"📋 *Заплановані пости:* {len(posts)}", ""]
                for p in posts:
                    preview = (p.get("text") or "")[:50]
                    sched = p.get("scheduled_at") or "?"
                    lines.append(f"• #{p['id']} — {sched}\n  _{preview}_")
                text = "\n".join(lines)

            kb_rows = []
            for p in posts[:10]:
                kb_rows.append([
                    InlineKeyboardButton(
                        f"🗑️ Видалити #{p['id']}",
                        callback_data=f"nb_delpost_{p['id']}",
                    )
                ])
            kb_rows.append([InlineKeyboardButton("◀️ Назад", callback_data="menu_back")])

            await q.edit_message_text(
                text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(kb_rows),
            )

        elif q.data == "menu_back":
            await q.edit_message_text(
                "👑 *GlowRoom Admin*\n\nОбери дію 👇",
                parse_mode="Markdown",
                reply_markup=main_keyboard(),
            )

        else:
            logger.warning("[NB] unknown menu data=%s", q.data)

    except Exception as e:
        logger.error("[NB] menu_handler ERROR data=%s\n%s", q.data, traceback.format_exc())
        try:
            await q.edit_message_text(
                f"❌ Помилка: `{type(e).__name__}: {str(e)[:200]}`",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("◀️ Назад", callback_data="menu_back")]]
                ),
            )
        except Exception:
            pass


# ═══════════════════════════════════════
#  DELETE SCHEDULED POST
# ═══════════════════════════════════════

async def nb_delete_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    try:
        await q.answer()
    except Exception:
        pass
    try:
        post_id = int(q.data.replace("nb_delpost_", ""))
        db.delete_scheduled_post(post_id)
        await q.edit_message_text(
            f"✅ Пост #{post_id} видалено.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("◀️ Назад", callback_data="menu_back")]]
            ),
        )
    except Exception as e:
        logger.exception("[NB] delete failed")
        await q.edit_message_text(
            f"❌ Помилка видалення: {e}",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("◀️ Назад", callback_data="menu_back")]]
            ),
        )


# ═══════════════════════════════════════
#  CREATE POST  (ConversationHandler)
# ═══════════════════════════════════════

async def create_post_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(update):
        await q.edit_message_text("❌ Немає доступу.")
        return ConversationHandler.END
    context.user_data.clear()
    await q.edit_message_text("✏️ Надішли *текст* поста:", parse_mode="Markdown")
    return POST_TEXT


async def post_get_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["post_text"] = update.message.text or ""
    await update.message.reply_text(
        "📸 Прикріпи *фото* або натисни кнопку:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("➡️ Без фото", callback_data="post_no_photo")]]
        ),
    )
    return POST_PHOTO


async def post_get_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["post_photo"] = update.message.photo[-1].file_id
    return await ask_schedule_type(update, context)


async def post_no_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["post_photo"] = None
    return await ask_schedule_type(update, context, query=q)


async def ask_schedule_type(update, context, query=None):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Надіслати зараз", callback_data="schedule_now")],
        [InlineKeyboardButton("⏰ Запланувати", callback_data="schedule_later")],
        [InlineKeyboardButton("❌ Скасувати", callback_data="schedule_cancel")],
    ])
    text = "⏱️ Коли надіслати?"
    if query:
        await query.edit_message_text(text, reply_markup=kb)
    else:
        await update.message.reply_text(text, reply_markup=kb)
    return POST_SCHEDULE_TYPE


async def post_schedule_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "schedule_cancel":
        await q.edit_message_text("❌ Скасовано.")
        context.user_data.clear()
        return ConversationHandler.END
    if q.data == "schedule_now":
        return await do_confirm(update, context, send_now=True, query=q)
    today = datetime.now()
    buttons = []
    for i in range(7):
        d = today + timedelta(days=i)
        label = d.strftime("%d.%m")
        buttons.append([InlineKeyboardButton(label, callback_data=f"postdate_{d.strftime('%Y-%m-%d')}")])
    await q.edit_message_text("📅 Оберіть дату:", reply_markup=InlineKeyboardMarkup(buttons))
    return POST_SCHEDULE_DATE


async def post_schedule_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    date_str = q.data.replace("postdate_", "")
    context.user_data["post_date"] = date_str
    hours = [[InlineKeyboardButton(f"{h:02d}:00", callback_data=f"posttime_{h:02d}:00")] for h in range(9, 22)]
    await q.edit_message_text(f"🕐 Час для {date_str}:", reply_markup=InlineKeyboardMarkup(hours))
    return POST_SCHEDULE_TIME


async def post_schedule_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    time_str = q.data.replace("posttime_", "")
    context.user_data["post_time"] = time_str
    return await do_confirm(update, context, send_now=False, query=q)


async def do_confirm(update, context, send_now, query=None):
    text = context.user_data.get("post_text", "")
    scheduled_label = "зараз" if send_now else f"{context.user_data.get('post_date')} {context.user_data.get('post_time')}"
    preview = f"📬 *Підтвердження*\n\n{text}\n\n⏰ _{scheduled_label}_"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Надіслати" if send_now else "✅ Запланувати", callback_data=f"post_confirm_{'now' if send_now else 'later'}")],
        [InlineKeyboardButton("❌ Скасувати", callback_data="post_confirm_cancel")],
    ])
    if query:
        await query.edit_message_text(preview, parse_mode="Markdown", reply_markup=kb)
    else:
        await update.message.reply_text(preview, parse_mode="Markdown", reply_markup=kb)
    return POST_CONFIRM


async def post_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "post_confirm_cancel":
        await q.edit_message_text("❌ Скасовано.")
        context.user_data.clear()
        return ConversationHandler.END
    text = context.user_data.get("post_text", "")
    photo = context.user_data.get("post_photo")
    if q.data == "post_confirm_now":
        try:
            count = await send_broadcast(context.bot, text, photo)
            await q.edit_message_text(f"✅ Надіслано {count} клієнтам.")
        except Exception as e:
            logger.exception("[NB] send now failed")
            await q.edit_message_text(f"❌ Помилка: {e}")
    else:
        date = context.user_data.get("post_date")
        time_s = context.user_data.get("post_time")
        scheduled_at = f"{date} {time_s}"
        try:
            post_id = db.create_scheduled_post(text, photo, scheduled_at)
            global scheduler
            try:
                if scheduler is not None:
                    run_at = datetime.strptime(scheduled_at, "%Y-%m-%d %H:%M")
                    if run_at > datetime.now():
                        scheduler.add_job(send_broadcast_job, "date", run_date=run_at, args=[context.bot, text, photo, post_id], id=f"post_{post_id}")
            except Exception:
                logger.exception("[NB] schedule add_job failed")
            await q.edit_message_text(f"✅ Заплановано на {scheduled_at} (#{post_id})")
        except Exception as e:
            logger.exception("[NB] schedule failed")
            await q.edit_message_text(f"❌ Помилка: {e}")
    context.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Скасовано.")
    context.user_data.clear()
    return ConversationHandler.END


# ═══════════════════════════════════════
#  BROADCAST
# ═══════════════════════════════════════

async def send_broadcast(bot, text, photo, post_id=None):
    try:
        clients = db.get_all_clients()
    except Exception:
        logger.exception("[NB] broadcast get_all_clients failed")
        return 0
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
            logger.warning("[NB] broadcast fail user=%s: %s", uid, e)
    if post_id:
        try:
            db.delete_scheduled_post(post_id)
        except Exception:
            logger.exception("[NB] delete scheduled failed")
    return sent


async def send_broadcast_job(bot, text, photo, post_id):
    try:
        await send_broadcast(bot, text, photo, post_id=post_id)
    except Exception:
        logger.exception("[NB] scheduled broadcast failed")
