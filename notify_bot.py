import os
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import database as db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

NOTIFY_TOKEN = os.getenv("NOTIFY_TOKEN", "8647746412:AAFD1ZRI9jbzr5GdgTkGCKzTI15UX9OvPM0")
MAIN_BOT_TOKEN = os.getenv("BOT_TOKEN", "8664438342:AAF1i1tHXRZXMsqMrPwXGtQsrjL1ZreEmuA")
ADMIN_IDS = [715653302, 456903781]

# Стани для створення посту
(POST_TEXT, POST_PHOTO, POST_SCHEDULE_TYPE, POST_SCHEDULE_DATE, POST_SCHEDULE_TIME, POST_CONFIRM) = range(6)

# Глобальний планувальник
scheduler = AsyncIOScheduler()


def is_admin(update: Update):
    return update.effective_user.id in ADMIN_IDS


# ══════════════════════════════════════════════════════
#  СТАРТ
# ══════════════════════════════════════════════════════

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("❌ Немає доступу.")
        return

    await update.message.reply_text(
        "👑 *GlowRoom Admin Bot*\n\n"
        "Тут ти можеш:\n"
        "📢 Створювати пости і розсилати їх клієнтам\n"
        "📅 Планувати розсилку на потрібний час\n"
        "👥 Бачити базу клієнтів\n\n"
        "Обери дію 👇",
        reply_markup=main_keyboard(),
        parse_mode="Markdown"
    )


def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Створити пост",      callback_data="menu_create_post")],
        [InlineKeyboardButton("📋 Заплановані пости",  callback_data="menu_scheduled")],
        [InlineKeyboardButton("👥 База клієнтів",      callback_data="menu_clients")],
    ])


async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "menu_clients":
        clients = db.get_all_clients()
        await query.edit_message_text(
            f"👥 *База клієнтів:* {len(clients)} чол.\n\n"
            + "\n".join([f"• {c['first_name']} @{c['username'] or '—'}" for c in clients[:30]])
            + ("\n\n_...і ще більше_" if len(clients) > 30 else ""),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="menu_back")]])
        )

    elif query.data == "menu_scheduled":
        posts = db.get_scheduled_posts()
        if not posts:
            await query.edit_message_text(
                "📋 Немає запланованих постів.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="menu_back")]])
            )
            return
        lines = ["📋 *Заплановані пости:*\n"]
        for p in posts:
            lines.append(f"🕐 {p['scheduled_at']}\n📝 {p['text'][:50]}...\n")
        await query.edit_message_text(
            "\n".join(lines),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="menu_back")]])
        )

    elif query.data == "menu_back":
        await query.edit_message_text(
            "👑 *GlowRoom Admin Bot*\n\nОбери дію 👇",
            reply_markup=main_keyboard(),
            parse_mode="Markdown"
        )


# ══════════════════════════════════════════════════════
#  СТВОРЕННЯ ПОСТУ
# ══════════════════════════════════════════════════════

async def create_post_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()

    await query.edit_message_text(
        "📝 *Створення посту*\n\n"
        "Напиши текст посту який побачать всі клієнти.\n\n"
        "_Можна використовувати емодзі 🎉_\n\n"
        "Для скасування: /cancel",
        parse_mode="Markdown"
    )
    return POST_TEXT


async def post_get_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['post_text'] = update.message.text

    await update.message.reply_text(
        "📸 Додай фото до посту або натисни *Без фото* 👇",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🚫 Без фото", callback_data="post_no_photo")]
        ])
    )
    return POST_PHOTO


async def post_get_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo = update.message.photo[-1]
    context.user_data['post_photo'] = photo.file_id
    return await ask_schedule_type(update, context)


async def post_no_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['post_photo'] = None
    return await ask_schedule_type(update, context, query=query)


async def ask_schedule_type(update, context, query=None):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 Відправити зараз",     callback_data="schedule_now")],
        [InlineKeyboardButton("⏰ Запланувати на час",   callback_data="schedule_later")],
    ])
    text = "⏰ *Коли відправити пост?*"

    if query:
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")
    return POST_SCHEDULE_TYPE


async def post_schedule_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "schedule_now":
        context.user_data['scheduled_at'] = None
        return await show_post_preview(query, context)

    # Запланувати — просимо дату
    today = datetime.now()
    keyboard = []
    days_ua = {"Mon": "Пн", "Tue": "Вт", "Wed": "Ср", "Thu": "Чт", "Fri": "Пт", "Sat": "Сб", "Sun": "Нд"}
    for i in range(0, 14):
        from datetime import timedelta
        day = today + timedelta(days=i)
        ua = days_ua.get(day.strftime("%a"), "")
        label = f"{day.strftime('%d.%m')} ({ua})"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"postdate_{day.strftime('%Y-%m-%d')}")])

    await query.edit_message_text(
        "📅 Обери дату розсилки:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return POST_SCHEDULE_DATE


async def post_schedule_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['post_date'] = query.data.replace("postdate_", "")

    # Вибір часу
    times = ["09:00", "10:00", "11:00", "12:00", "13:00", "14:00",
             "15:00", "16:00", "17:00", "18:00", "19:00", "20:00"]
    keyboard = []
    row = []
    for t in times:
        row.append(InlineKeyboardButton(t, callback_data=f"posttime_{t}"))
        if len(row) == 4:
            keyboard.append(row); row = []
    if row:
        keyboard.append(row)

    await query.edit_message_text(
        "⏰ Обери час розсилки:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return POST_SCHEDULE_TIME


async def post_schedule_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    t = query.data.replace("posttime_", "")
    d = context.user_data['post_date']
    context.user_data['scheduled_at'] = f"{d} {t}"
    return await show_post_preview(query, context)


async def show_post_preview(query, context):
    d = context.user_data
    text = d['post_text']
    scheduled = d.get('scheduled_at')
    photo = d.get('post_photo')

    schedule_text = f"⏰ Час розсилки: {scheduled}" if scheduled else "📤 Відправити: зараз"

    preview = (
        f"👁 *Попередній перегляд посту:*\n\n"
        f"{text}\n\n"
        f"{'📸 З фото' if photo else '🚫 Без фото'}\n"
        f"{schedule_text}\n\n"
        f"Підтвердити?"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Підтвердити та розіслати", callback_data="post_confirm_yes")],
        [InlineKeyboardButton("❌ Скасувати",                callback_data="post_confirm_no")],
    ])
    await query.edit_message_text(preview, reply_markup=keyboard, parse_mode="Markdown")
    return POST_CONFIRM


async def post_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "post_confirm_no":
        await query.edit_message_text(
            "Скасовано.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Меню", callback_data="menu_back")]])
        )
        return ConversationHandler.END

    d = context.user_data
    text = d['post_text']
    photo = d.get('post_photo')
    scheduled_at = d.get('scheduled_at')

    if scheduled_at:
        # Зберігаємо в БД і плануємо
        post_id = db.save_scheduled_post(text, photo, scheduled_at)
        dt = datetime.strptime(scheduled_at, "%Y-%m-%d %H:%M")
        scheduler.add_job(
            send_broadcast,
            'date',
            run_date=dt,
            args=[context.application, text, photo, post_id],
            id=f"post_{post_id}"
        )
        await query.edit_message_text(
            f"✅ Пост заплановано на {scheduled_at}!\n\nКлієнти отримають його автоматично.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Меню", callback_data="menu_back")]])
        )
    else:
        # Відправляємо зараз
        await query.edit_message_text("📤 Розсилаю пост...")
        sent, failed = await send_broadcast(context.application, text, photo)
        await context.bot.send_message(
            query.from_user.id,
            f"✅ Розсилка завершена!\nВідправлено: {sent} | Не доставлено: {failed}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Меню", callback_data="menu_back")]])
        )

    return ConversationHandler.END


async def send_broadcast(application, text, photo, post_id=None):
    from telegram import Bot as TGBot
    main_bot = TGBot(token=MAIN_BOT_TOKEN)
    clients = db.get_all_clients()
    sent = failed = 0

    for client in clients:
        try:
            if photo:
                await main_bot.send_photo(client['user_id'], photo=photo, caption=text)
            else:
                await main_bot.send_message(client['user_id'], text)
            sent += 1
        except Exception as e:
            logger.error(f"Broadcast error {client['user_id']}: {e}")
            failed += 1

    if post_id:
        db.mark_post_sent(post_id)

    return sent, failed


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Скасовано. Напиши /start щоб почати знову.")
    return ConversationHandler.END


# ══════════════════════════════════════════════════════
#  ЗАПУСК
# ══════════════════════════════════════════════════════

def main():
    db.init_db()
    app = Application.builder().token(NOTIFY_TOKEN).build()

    scheduler.start()

    # Відновлюємо заплановані пости після перезапуску
    posts = db.get_scheduled_posts()
    for p in posts:
        try:
            dt = datetime.strptime(p['scheduled_at'], "%Y-%m-%d %H:%M")
            if dt > datetime.now():
                scheduler.add_job(
                    send_broadcast,
                    'date',
                    run_date=dt,
                    args=[app, p['text'], p['photo'], p['id']],
                    id=f"post_{p['id']}"
                )
        except Exception as e:
            logger.error(f"Restore scheduled post error: {e}")

    post_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(create_post_start, pattern="^menu_create_post$")],
        states={
            POST_TEXT:          [MessageHandler(filters.TEXT & ~filters.COMMAND, post_get_text)],
            POST_PHOTO:         [
                MessageHandler(filters.PHOTO, post_get_photo),
                CallbackQueryHandler(post_no_photo, pattern="^post_no_photo$"),
            ],
            POST_SCHEDULE_TYPE: [CallbackQueryHandler(post_schedule_type, pattern="^schedule_")],
            POST_SCHEDULE_DATE: [CallbackQueryHandler(post_schedule_date, pattern="^postdate_")],
            POST_SCHEDULE_TIME: [CallbackQueryHandler(post_schedule_time, pattern="^posttime_")],
            POST_CONFIRM:       [CallbackQueryHandler(post_confirm, pattern="^post_confirm_")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(post_conv)
    app.add_handler(CallbackQueryHandler(menu_handler, pattern="^menu_"))

    logger.info("Admin bot запущено!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
