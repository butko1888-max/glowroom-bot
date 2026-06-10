import os
import logging
import json
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import database as db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

NOTIFY_TOKEN  = os.getenv("NOTIFY_TOKEN",  "8647746412:AAFD1ZRI9jbzr5GdgTkGCKzTI15UX9OvPM0")
MAIN_TOKEN    = os.getenv("BOT_TOKEN",     "8664438342:AAF1i1tHXRZXMsqMrPwXGtQsrjL1ZreEmuA")
ADMIN_IDS     = [715653302, 456903781]

# Стани для створення посту
(
    POST_TEXT,
    POST_PHOTO,
    POST_SCHEDULE_CHOICE,
    POST_DATE,
    POST_TIME,
    POST_DURATION,
) = range(20, 26)

# Зберігаємо заплановані пости в пам'яті
scheduled_posts = {}   # id -> {text, photo, send_at, remove_at, job_id}
post_counter = 0

scheduler = AsyncIOScheduler()


# ══════════════════════════════════════════════════════
#  ПЕРЕВІРКА АДМІНА
# ══════════════════════════════════════════════════════

def is_admin(update: Update) -> bool:
    return update.effective_user.id in ADMIN_IDS


# ══════════════════════════════════════════════════════
#  ГОЛОВНЕ МЕНЮ
# ══════════════════════════════════════════════════════

def admin_menu():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📢 Створити пост"),   KeyboardButton("📋 Заплановані пости")],
        [KeyboardButton("👥 База клієнтів"),   KeyboardButton("📅 Записи на сьогодні")],
        [KeyboardButton("📆 Всі майбутні записи")],
    ], resize_keyboard=True)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("❌ Немає доступу.")
        return
    await update.message.reply_text(
        "👑 Адмін-панель GlowRoom\n\nОбери дію 👇",
        reply_markup=admin_menu()
    )


async def handle_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    text = update.message.text
    if text == "👥 База клієнтів":
        await show_clients(update, context)
    elif text == "📅 Записи на сьогодні":
        await show_today(update, context)
    elif text == "📆 Всі майбутні записи":
        await show_upcoming(update, context)
    elif text == "📋 Заплановані пости":
        await show_scheduled(update, context)
    elif text == "📢 Створити пост":
        return await create_post_start(update, context)


# ══════════════════════════════════════════════════════
#  ЗАПИСИ / КЛІЄНТИ
# ══════════════════════════════════════════════════════

SERVICES = {
    "brow_lam":        {"name": "Комплекс ламінування (ламі + фарба)", "price": 700,  "emoji": "💎"},
    "brow_color":      {"name": "Фарбування + корекція",                "price": 500,  "emoji": "🎨"},
    "brow_correction": {"name": "Корекція (віск / пінцет)",             "price": 300,  "emoji": "✂️"},
    "brow_bleach":     {"name": "Освітлення + тонування + корекція",    "price": 600,  "emoji": "🌟"},
    "lash_lam":        {"name": "Комплекс ламінування (+ догляд)",      "price": 750,  "emoji": "💎"},
    "lash_color":      {"name": "Фарбування вій",                       "price": 300,  "emoji": "🎨"},
    "full_complex":    {"name": "Ламі вій + ламі брів",                 "price": 1300, "emoji": "👑"},
    "waxing_other":    {"name": "Вакcинг інших зон",                    "price": 100,  "emoji": "🪶"},
}


async def show_clients(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clients = db.get_all_clients()
    if not clients:
        await update.message.reply_text("База клієнтів порожня.")
        return
    lines = [f"👥 База клієнтів: {len(clients)} чол.\n"]
    for c in clients:
        uname = f"@{c['username']}" if c['username'] else "—"
        lines.append(f"👤 {c['first_name']} {uname}")
    await update.message.reply_text("\n".join(lines))


async def show_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = datetime.now().strftime("%Y-%m-%d")
    bookings = db.get_bookings_by_date(today)
    if not bookings:
        await update.message.reply_text("📅 На сьогодні записів немає.")
        return
    lines = [f"📅 Записи на сьогодні ({datetime.now().strftime('%d.%m.%Y')}):\n"]
    for b in bookings:
        s = SERVICES.get(b['service_id'], {})
        lines.append(f"⏰ {b['time']} — {b['name']} ({b['phone']})\n{s.get('emoji','💅')} {s.get('name', b['service_id'])}\n")
    await update.message.reply_text("\n".join(lines))


async def show_upcoming(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = datetime.now().strftime("%Y-%m-%d")
    bookings = db.get_upcoming_bookings(today)
    if not bookings:
        await update.message.reply_text("Майбутніх записів немає.")
        return
    lines = ["📆 Всі майбутні записи:\n"]
    for b in bookings:
        s = SERVICES.get(b['service_id'], {})
        date_d = datetime.strptime(b['date'], "%Y-%m-%d").strftime("%d.%m")
        lines.append(f"📅 {date_d} {b['time']} — {b['name']} | 📱 {b['phone']}\n{s.get('emoji','💅')} {s.get('name', b['service_id'])}\n")
    await update.message.reply_text("\n".join(lines))


# ══════════════════════════════════════════════════════
#  СТВОРЕННЯ ПОСТУ
# ══════════════════════════════════════════════════════

async def create_post_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['post'] = {}
    await update.message.reply_text(
        "📢 Створення посту\n\n"
        "Крок 1/4 — Напиши текст посту:",
        reply_markup=ReplyKeyboardMarkup([[KeyboardButton("❌ Скасувати")]], resize_keyboard=True)
    )
    return POST_TEXT


async def post_get_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Скасувати":
        await update.message.reply_text("Скасовано.", reply_markup=admin_menu())
        return ConversationHandler.END

    context.user_data['post']['text'] = update.message.text
    await update.message.reply_text(
        "Крок 2/4 — Надішли фото для посту (або натисни кнопку щоб пропустити):",
        reply_markup=ReplyKeyboardMarkup(
            [[KeyboardButton("⏭ Без фото")], [KeyboardButton("❌ Скасувати")]],
            resize_keyboard=True
        )
    )
    return POST_PHOTO


async def post_get_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Скасувати":
        await update.message.reply_text("Скасовано.", reply_markup=admin_menu())
        return ConversationHandler.END

    if update.message.photo:
        context.user_data['post']['photo'] = update.message.photo[-1].file_id
    else:
        context.user_data['post']['photo'] = None

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 Відправити зараз", callback_data="post_now")],
        [InlineKeyboardButton("⏰ Запланувати на потім", callback_data="post_schedule")],
    ])
    await update.message.reply_text(
        "Крок 3/4 — Коли відправити пост?",
        reply_markup=keyboard
    )
    return POST_SCHEDULE_CHOICE


async def post_schedule_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "post_now":
        # Питаємо скільки часу пост "живе"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("1 година",  callback_data="dur_1")],
            [InlineKeyboardButton("3 години",  callback_data="dur_3")],
            [InlineKeyboardButton("6 годин",   callback_data="dur_6")],
            [InlineKeyboardButton("12 годин",  callback_data="dur_12")],
            [InlineKeyboardButton("24 години", callback_data="dur_24")],
            [InlineKeyboardButton("Назавжди",  callback_data="dur_0")],
        ])
        context.user_data['post']['send_now'] = True
        await query.edit_message_text(
            "Крок 4/4 — Скільки часу пост буде закріплений?\n(Після цього часу бот надішле повідомлення що акція закінчилась)",
            reply_markup=keyboard
        )
        return POST_DURATION

    else:  # schedule
        # Пропонуємо дати
        today = datetime.now()
        keyboard = []
        days_ua = {"Mon": "Пн", "Tue": "Вт", "Wed": "Ср", "Thu": "Чт", "Fri": "Пт", "Sat": "Сб", "Sun": "Нд"}
        for i in range(0, 14):
            day = today + __import__('datetime').timedelta(days=i)
            ua = days_ua.get(day.strftime("%a"), "")
            label = f"{day.strftime('%d.%m')} ({ua})"
            keyboard.append([InlineKeyboardButton(label, callback_data=f"pdate_{day.strftime('%Y-%m-%d')}")])
        context.user_data['post']['send_now'] = False
        await query.edit_message_text(
            "Обери дату публікації 📅",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return POST_DATE


async def post_get_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['post']['send_date'] = query.data[6:]  # обрізаємо "pdate_"

    times = ["09:00", "10:00", "11:00", "12:00", "13:00", "14:00",
             "15:00", "16:00", "17:00", "18:00", "19:00", "20:00"]
    row, keyboard = [], []
    for t in times:
        row.append(InlineKeyboardButton(t, callback_data=f"ptime_{t}"))
        if len(row) == 4:
            keyboard.append(row); row = []
    if row:
        keyboard.append(row)

    await query.edit_message_text(
        "Обери час публікації ⏰",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return POST_TIME


async def post_get_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['post']['send_time'] = query.data[6:]  # обрізаємо "ptime_"

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("1 година",  callback_data="dur_1")],
        [InlineKeyboardButton("3 години",  callback_data="dur_3")],
        [InlineKeyboardButton("6 годин",   callback_data="dur_6")],
        [InlineKeyboardButton("12 годин",  callback_data="dur_12")],
        [InlineKeyboardButton("24 години", callback_data="dur_24")],
        [InlineKeyboardButton("Назавжди",  callback_data="dur_0")],
    ])
    await query.edit_message_text(
        "Скільки часу пост буде активним?\n(Після цього часу бот надішле повідомлення що акція закінчилась)",
        reply_markup=keyboard
    )
    return POST_DURATION


async def post_get_duration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global post_counter
    query = update.callback_query
    await query.answer()

    duration_h = int(query.data[4:])  # обрізаємо "dur_"
    post = context.user_data['post']
    post['duration_h'] = duration_h

    # Визначаємо час відправки
    if post.get('send_now'):
        send_at = datetime.now()
    else:
        send_at = datetime.strptime(
            f"{post['send_date']} {post['send_time']}",
            "%Y-%m-%d %H:%M"
        )

    # Час видалення (завершення)
    remove_at = None
    if duration_h > 0:
        remove_at = send_at + __import__('datetime').timedelta(hours=duration_h)

    post_counter += 1
    pid = post_counter
    scheduled_posts[pid] = {
        'text': post['text'],
        'photo': post.get('photo'),
        'send_at': send_at,
        'remove_at': remove_at,
        'duration_h': duration_h,
    }

    # Планування відправки
    scheduler.add_job(
        send_post_to_all,
        'date',
        run_date=send_at,
        args=[context.application, pid],
        id=f"post_send_{pid}"
    )

    # Планування завершення
    if remove_at:
        scheduler.add_job(
            send_post_end,
            'date',
            run_date=remove_at,
            args=[context.application, pid],
            id=f"post_end_{pid}"
        )

    # Підтвердження
    send_str = send_at.strftime("%d.%m.%Y о %H:%M")
    dur_str = f"{duration_h} год." if duration_h > 0 else "назавжди"
    remove_str = remove_at.strftime("%d.%m.%Y о %H:%M") if remove_at else "не обмежено"

    await query.edit_message_text(
        f"✅ Пост заплановано!\n\n"
        f"📤 Відправка: {send_str}\n"
        f"⏱ Активний: {dur_str}\n"
        f"🔚 Завершення: {remove_str}\n\n"
        f"Пост буде розіслано всім клієнтам."
    )
    await context.application.bot.send_message(
        update.effective_user.id,
        "Повертаємось до меню 👇",
        reply_markup=admin_menu()
    )
    return ConversationHandler.END


# ══════════════════════════════════════════════════════
#  ВІДПРАВКА ПОСТУ ВСІМ КЛІЄНТАМ
# ══════════════════════════════════════════════════════

async def send_post_to_all(application, pid: int):
    post = scheduled_posts.get(pid)
    if not post:
        return

    clients = db.get_all_clients()
    sent = failed = 0

    for client in clients:
        try:
            if post['photo']:
                await application.bot.send_photo(
                    client['user_id'],
                    photo=post['photo'],
                    caption=post['text']
                )
            else:
                await application.bot.send_message(
                    client['user_id'],
                    post['text']
                )
            sent += 1
        except Exception as e:
            failed += 1
            logger.error(f"Post send error {client['user_id']}: {e}")

    logger.info(f"Post {pid} sent: {sent} ok, {failed} failed")

    # Повідомлення адмінам про успішну відправку
    for admin_id in ADMIN_IDS:
        try:
            await application.bot.send_message(
                admin_id,
                f"✅ Пост розіслано!\nВідправлено: {sent} | Не доставлено: {failed}"
            )
        except Exception:
            pass


async def send_post_end(application, pid: int):
    """Повідомлення клієнтам що акція завершилась"""
    post = scheduled_posts.get(pid)
    if not post:
        return

    clients = db.get_all_clients()
    for client in clients:
        try:
            await application.bot.send_message(
                client['user_id'],
                "⏰ Нагадуємо: термін акції завершився.\nСлідкуй за нашими новинами! 💅"
            )
        except Exception:
            pass

    # Повідомлення адмінам
    for admin_id in ADMIN_IDS:
        try:
            await application.bot.send_message(
                admin_id,
                f"🔚 Пост #{pid} завершив дію."
            )
        except Exception:
            pass

    # Видаляємо з пам'яті
    scheduled_posts.pop(pid, None)


# ══════════════════════════════════════════════════════
#  СПИСОК ЗАПЛАНОВАНИХ ПОСТІВ
# ══════════════════════════════════════════════════════

async def show_scheduled(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not scheduled_posts:
        await update.message.reply_text("📋 Немає запланованих постів.")
        return

    lines = ["📋 Заплановані пости:\n"]
    for pid, p in scheduled_posts.items():
        send_str = p['send_at'].strftime("%d.%m.%Y о %H:%M")
        dur_str = f"{p['duration_h']} год." if p['duration_h'] > 0 else "назавжди"
        preview = p['text'][:50] + "..." if len(p['text']) > 50 else p['text']
        lines.append(f"#{pid} — {send_str} ({dur_str})\n{preview}\n")

    keyboard = []
    for pid in scheduled_posts:
        keyboard.append([InlineKeyboardButton(f"❌ Скасувати пост #{pid}", callback_data=f"cancel_post_{pid}")])

    await update.message.reply_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
    )


async def cancel_post_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(update):
        return

    pid = int(query.data[12:])  # обрізаємо "cancel_post_"

    # Зупиняємо jobs
    for job_id in [f"post_send_{pid}", f"post_end_{pid}"]:
        try:
            scheduler.remove_job(job_id)
        except Exception:
            pass

    scheduled_posts.pop(pid, None)
    await query.edit_message_text(f"✅ Пост #{pid} скасовано.")


async def cancel_conv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Скасовано.", reply_markup=admin_menu())
    return ConversationHandler.END


# ══════════════════════════════════════════════════════
#  ЗАПУСК
# ══════════════════════════════════════════════════════

def main():
    db.init_db()
    app = Application.builder().token(NOTIFY_TOKEN).build()

    scheduler.start()

    post_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📢 Створити пост$"), create_post_start)],
        states={
            POST_TEXT:            [MessageHandler(filters.TEXT & ~filters.COMMAND, post_get_text)],
            POST_PHOTO:           [
                MessageHandler(filters.PHOTO, post_get_photo),
                MessageHandler(filters.Regex("^⏭ Без фото$"), post_get_photo),
                MessageHandler(filters.Regex("^❌ Скасувати$"), cancel_conv),
            ],
            POST_SCHEDULE_CHOICE: [CallbackQueryHandler(post_schedule_choice, pattern="^post_")],
            POST_DATE:            [CallbackQueryHandler(post_get_date, pattern="^pdate_")],
            POST_TIME:            [CallbackQueryHandler(post_get_time, pattern="^ptime_")],
            POST_DURATION:        [CallbackQueryHandler(post_get_duration, pattern="^dur_")],
        },
        fallbacks=[
            MessageHandler(filters.Regex("^❌ Скасувати$"), cancel_conv),
            CommandHandler("cancel", cancel_conv),
        ],
        per_message=False,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(post_conv)
    app.add_handler(CallbackQueryHandler(cancel_post_callback, pattern="^cancel_post_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, handle_menu))

    logger.info("Адмін-бот запущено!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
