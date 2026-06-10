import os
import asyncio
import logging
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import database as db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN    = os.getenv("BOT_TOKEN",    "8664438342:AAF1i1tHXRZXMsqMrPwXGtQsrjL1ZreEmuA")
NOTIFY_TOKEN = os.getenv("NOTIFY_TOKEN", "8647746412:AAFD1ZRI9jbzr5GdgTkGCKzTI15UX9OvPM0")
ADMIN_IDS    = [715653302, 456903781]

# ══════════════════════════════════════════════════════
#  ДАНІ
# ══════════════════════════════════════════════════════

SELECT_CATEGORY, SELECT_SERVICE, CONFIRM_SERVICE, SELECT_DATE, SELECT_TIME, ENTER_NAME, ENTER_PHONE, CONFIRM_BOOKING = range(8)
POST_TEXT, POST_PHOTO, POST_SCHEDULE_TYPE, POST_SCHEDULE_DATE, POST_SCHEDULE_TIME, POST_DELETE_TIME, POST_CONFIRM = range(10, 17)

SERVICES = {
    "brow_lam":        {"cat": "brows",   "name": "Комплекс ламінування (ламі + фарба)", "price": 700,  "emoji": "💎"},
    "brow_color":      {"cat": "brows",   "name": "Фарбування + корекція",                "price": 500,  "emoji": "🎨"},
    "brow_correction": {"cat": "brows",   "name": "Корекція (віск / пінцет)",             "price": 300,  "emoji": "✂️"},
    "brow_bleach":     {"cat": "brows",   "name": "Освітлення + тонування + корекція",    "price": 600,  "emoji": "🌟"},
    "lash_lam":        {"cat": "lashes",  "name": "Комплекс ламінування (+ догляд)",      "price": 750,  "emoji": "💎"},
    "lash_color":      {"cat": "lashes",  "name": "Фарбування вій",                       "price": 300,  "emoji": "🎨"},
    "full_complex":    {"cat": "complex", "name": "Ламі вій + ламі брів",                 "price": 1300, "emoji": "👑"},
    "waxing_other":    {"cat": "waxing",  "name": "Вакcинг інших зон",                    "price": 100,  "emoji": "🪶"},
}
CATEGORIES = {
    "brows":   "🌿 Брови",
    "lashes":  "✨ Вії",
    "complex": "👑 Комплекс",
    "waxing":  "🪶 Вакcинг",
}
AVAILABLE_TIMES = ["10:00","11:00","12:00","13:00","14:00","15:00","16:00","17:00","18:00","19:00"]

# ══════════════════════════════════════════════════════
#  ПЕРШИЙ БОТ — клієнтський
# ══════════════════════════════════════════════════════

def main_menu_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📅 Записатись"), KeyboardButton("💰 Прайс-лист")],
        [KeyboardButton("📋 Мої записи"), KeyboardButton("📞 Контакти")],
        [KeyboardButton("🔄 Перезавантажити")],
    ], resize_keyboard=True)

def is_admin(update): return update.effective_user.id in ADMIN_IDS

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.add_client(user.id, user.username or "", user.first_name or "")
    await update.message.reply_text(
        f"Привіт, {user.first_name}! 👋\n\nЛаскаво просимо до бота студії краси ✨\n"
        "Тут ти можеш записатись на послуги, переглянути прайс та керувати своїми записами.\n\nОбери що тебе цікавить 👇",
        reply_markup=main_menu_keyboard()
    )

async def handle_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "💰 Прайс-лист":    await show_pricelist(update, context)
    elif text == "📋 Мої записи":  await show_my_bookings(update, context)
    elif text == "📞 Контакти":    await show_contacts(update, context)
    elif text == "📅 Записатись":  return await booking_start(update, context)
    elif text == "🔄 Перезавантажити": return await start(update, context)

async def show_pricelist(update, context):
    lines = ["💅 *Прайс-лист послуг*\n"]
    for cat_key, cat_name in CATEGORIES.items():
        svcs = [s for s in SERVICES.values() if s['cat'] == cat_key]
        if svcs:
            lines.append(f"*{cat_name}*")
            for s in svcs: lines.append(f"{s['emoji']} {s['name']} — *{s['price']} грн*")
            lines.append("")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def show_contacts(update, context):
    await update.message.reply_text(
        "📞 Контакти\n\n👩 Майстер: Кіра\n💬 Telegram: @Butko_Kira\n"
        "📍 Адреса: ЖК Славутич, Зарічна 4к1\n🕐 Години роботи: 10:00 — 20:00\n\nТакож можна написати мені напряму 👆"
    )

async def show_my_bookings(update, context):
    bookings = db.get_client_bookings(update.effective_user.id)
    if not bookings:
        await update.message.reply_text("У тебе поки немає активних записів.\n\nНатисни 📅 *Записатись*!", parse_mode="Markdown")
        return
    lines = ["📋 *Твої записи:*\n"]
    for b in bookings:
        svc = SERVICES.get(b['service_id'], {})
        lines.append(f"📌 {svc.get('emoji','💅')} {svc.get('name', b['service_id'])}\n📅 {b['date']} о {b['time']}\n")
    await update.message.reply_text("\n".join(lines))

async def booking_start(update, context):
    keyboard = [[InlineKeyboardButton(name, callback_data=f"cat_{key}")] for key, name in CATEGORIES.items()]
    await update.message.reply_text("Обери категорію 👇", reply_markup=InlineKeyboardMarkup(keyboard))
    return SELECT_CATEGORY

async def step_select_category(update, context):
    query = update.callback_query; await query.answer()
    cat_key = query.data[4:]
    svcs = {k: v for k, v in SERVICES.items() if v['cat'] == cat_key}
    keyboard = [[InlineKeyboardButton(f"{v['emoji']} {v['name']} — {v['price']} грн", callback_data=f"svc_{k}")] for k, v in svcs.items()]
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="back_to_categories")])
    await query.edit_message_text(f"*{CATEGORIES[cat_key]}* — обери послугу 👇", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return SELECT_SERVICE

async def step_select_service(update, context):
    query = update.callback_query; await query.answer()
    if query.data == "back_to_categories":
        keyboard = [[InlineKeyboardButton(name, callback_data=f"cat_{key}")] for key, name in CATEGORIES.items()]
        await query.edit_message_text("Обери категорію 👇", reply_markup=InlineKeyboardMarkup(keyboard))
        return SELECT_CATEGORY
    svc_id = query.data[4:]; context.user_data['service_id'] = svc_id; s = SERVICES[svc_id]
    await query.edit_message_text(
        f"{s['emoji']} *{s['name']}*\n\n💰 Вартість: *{s['price']} грн*\n\nХочеш записатись?",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📅 Записатись", callback_data="do_booking")],[InlineKeyboardButton("◀️ Назад", callback_data=f"back_to_cat_{s['cat']}")]]),
        parse_mode="Markdown"
    )
    return CONFIRM_SERVICE

async def step_confirm_service(update, context):
    query = update.callback_query; await query.answer()
    if query.data.startswith("back_to_cat_"):
        cat_key = query.data[12:]
        svcs = {k: v for k, v in SERVICES.items() if v['cat'] == cat_key}
        keyboard = [[InlineKeyboardButton(f"{v['emoji']} {v['name']} — {v['price']} грн", callback_data=f"svc_{k}")] for k, v in svcs.items()]
        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="back_to_categories")])
        await query.edit_message_text(f"*{CATEGORIES[cat_key]}* — обери послугу 👇", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return SELECT_SERVICE
    days_ua = {"Mon":"Пн","Tue":"Вт","Wed":"Ср","Thu":"Чт","Fri":"Пт","Sat":"Сб","Sun":"Нд"}
    keyboard = []
    for i in range(1, 15):
        day = datetime.now() + timedelta(days=i)
        ua = days_ua.get(day.strftime("%a"), "")
        keyboard.append([InlineKeyboardButton(f"{day.strftime('%d.%m')} ({ua})", callback_data=f"date_{day.strftime('%Y-%m-%d')}")])
    await query.edit_message_text(f"✅ *{SERVICES[context.user_data['service_id']]['name']}*\n\nОбери дату 📅", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return SELECT_DATE

async def step_select_date(update, context):
    query = update.callback_query; await query.answer()
    date_str = query.data[5:]; context.user_data['date'] = date_str
    booked = db.get_booked_times(date_str)
    row, keyboard = [], []
    for t in AVAILABLE_TIMES:
        if t not in booked:
            row.append(InlineKeyboardButton(t, callback_data=f"time_{t}"))
            if len(row) == 4: keyboard.append(row); row = []
    if row: keyboard.append(row)
    if not keyboard:
        await query.edit_message_text("На жаль, на цю дату всі слоти зайняті 😔\nОбери іншу дату /start")
        return ConversationHandler.END
    date_display = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d.%m.%Y")
    await query.edit_message_text(f"📅 Дата: *{date_display}*\n\nОбери зручний час ⏰", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return SELECT_TIME

async def step_select_time(update, context):
    query = update.callback_query; await query.answer()
    context.user_data['time'] = query.data[5:]
    await query.edit_message_text("Як тебе звати? 👤\n\nВведи своє ім'я:")
    return ENTER_NAME

async def step_enter_name(update, context):
    context.user_data['client_name'] = update.message.text.strip()
    await update.message.reply_text("Введи свій номер телефону 📱\n\nНаприклад: +380671234567")
    return ENTER_PHONE

async def step_enter_phone(update, context):
    d = context.user_data; d['phone'] = update.message.text.strip()
    s = SERVICES[d['service_id']]; date_display = datetime.strptime(d['date'], "%Y-%m-%d").strftime("%d.%m.%Y")
    await update.message.reply_text(
        f"📋 *Перевір дані запису:*\n\n{s['emoji']} {s['name']}\n💰 {s['price']} грн\n📅 {date_display} о {d['time']}\n👤 {d['client_name']}\n📱 {d['phone']}\n\nВсе вірно?",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Підтвердити", callback_data="confirm_yes"), InlineKeyboardButton("❌ Скасувати", callback_data="confirm_no")]]),
        parse_mode="Markdown"
    )
    return CONFIRM_BOOKING

async def step_confirm_booking(update, context):
    query = update.callback_query; await query.answer()
    if query.data == "confirm_no":
        await query.edit_message_text("Запис скасовано. Натисни 📅 Записатись щоб почати знову.")
        return ConversationHandler.END
    d = context.user_data; user = update.effective_user; s = SERVICES[d['service_id']]
    date_display = datetime.strptime(d['date'], "%Y-%m-%d").strftime("%d.%m.%Y")
    db.create_booking(user_id=user.id, service_id=d['service_id'], date=d['date'], time=d['time'], name=d['client_name'], phone=d['phone'])
    await query.edit_message_text(
        f"🎉 Запис підтверджено!\n\n{s['emoji']} {s['name']}\n📅 {date_display} о {d['time']}\n\n🔔 Я нагадаю тобі за добу та за годину до візиту!\nЯкщо потрібно перенести — напиши @Butko_Kira"
    )
    msg = (f"🆕 Новий запис!\n\n👤 {d['client_name']}\n📱 {d['phone']}\n{s['emoji']} {s['name']} — {s['price']} грн\n📅 {date_display} о {d['time']}\n🔗 @{user.username or '—'} (ID: {user.id})")
    from telegram import Bot as TGBot
    notify_bot = TGBot(token=NOTIFY_TOKEN)
    for admin_id in ADMIN_IDS:
        try: await notify_bot.send_message(admin_id, msg)
        except Exception as e: logger.error(f"Notify error {admin_id}: {e}")
    return ConversationHandler.END

async def cancel(update, context):
    await update.message.reply_text("Скасовано.", reply_markup=main_menu_keyboard())
    return ConversationHandler.END

async def admin_panel(update, context):
    if not is_admin(update): await update.message.reply_text("❌ Немає доступу."); return
    await update.message.reply_text("👑 *Панель адміністратора*",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📅 Записи на сьогодні",  callback_data="admin_today")],
            [InlineKeyboardButton("📋 Всі майбутні записи", callback_data="admin_upcoming")],
            [InlineKeyboardButton("👥 База клієнтів",       callback_data="admin_clients")],
        ]), parse_mode="Markdown")

async def admin_callback(update, context):
    query = update.callback_query; await query.answer()
    if not is_admin(update): return
    if query.data == "admin_today":
        today = datetime.now().strftime("%Y-%m-%d")
        bookings = db.get_bookings_by_date(today)
        if not bookings: await query.edit_message_text("📅 На сьогодні записів немає."); return
        lines = [f"📅 Записи на сьогодні ({datetime.now().strftime('%d.%m.%Y')}):\n"]
        for b in bookings:
            s = SERVICES.get(b['service_id'], {}); lines.append(f"⏰ {b['time']} — {b['name']} ({b['phone']})\n{s.get('emoji','💅')} {s.get('name','')}\n")
        await query.edit_message_text("\n".join(lines))
    elif query.data == "admin_upcoming":
        today = datetime.now().strftime("%Y-%m-%d")
        bookings = db.get_upcoming_bookings(today)
        if not bookings: await query.edit_message_text("Майбутніх записів немає."); return
        lines = ["📋 *Всі майбутні записи:*\n"]
        for b in bookings:
            s = SERVICES.get(b['service_id'], {}); date_d = datetime.strptime(b['date'], "%Y-%m-%d").strftime("%d.%m")
            lines.append(f"📅 {date_d} {b['time']} — {b['name']} | 📱 {b['phone']}\n{s.get('emoji','💅')} {s.get('name','')}\n")
        await query.edit_message_text("\n".join(lines))
    elif query.data == "admin_clients":
        clients = db.get_all_clients()
        await query.edit_message_text(f"👥 *База клієнтів:* {len(clients)} чол.", parse_mode="Markdown")

async def send_reminders_24h(application):
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    for b in db.get_bookings_by_date(tomorrow):
        s = SERVICES.get(b['service_id'], {}); date_display = datetime.strptime(b['date'], "%Y-%m-%d").strftime("%d.%m.%Y")
        try:
            await application.bot.send_message(b['user_id'], f"🔔 Нагадування про запис\n\nЗавтра у тебе запис!\n\n{s.get('emoji','💅')} {s.get('name','')}\n📅 {date_display} о {b['time']}\n\nЧекаємо тебе! 🤗\nЯкщо потрібно перенести — напиши @Butko_Kira")
        except Exception as e: logger.error(f"24h reminder error {b['user_id']}: {e}")

async def send_reminders_1h(application):
    now = datetime.now(); target_time = (now + timedelta(hours=1)).strftime("%H:00"); today = now.strftime("%Y-%m-%d")
    for b in db.get_bookings_by_date(today):
        if b['time'] == target_time:
            s = SERVICES.get(b['service_id'], {})
            try: await application.bot.send_message(b['user_id'], f"⏰ Через годину твій запис!\n\n{s.get('emoji','💅')} {s.get('name','')}\n🕐 о {b['time']}\n📍 ЖК Славутич, Зарічна 4к1\n\nДо зустрічі! ✨")
            except Exception as e: logger.error(f"1h reminder error {b['user_id']}: {e}")

# ══════════════════════════════════════════════════════
#  ДРУГИЙ БОТ — адмін/розсилка
# ══════════════════════════════════════════════════════

async def nb_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.add_client(user.id, user.username or "", user.first_name or "")
    if not is_admin(update): await update.message.reply_text("❌ Немає доступу."); return
    await update.message.reply_text(
        "👑 *GlowRoom Admin*\n\nОбери дію 👇",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📝 Створити пост",     callback_data="nb_create_post")],
            [InlineKeyboardButton("📋 Заплановані пости", callback_data="nb_scheduled")],
            [InlineKeyboardButton("👥 База клієнтів",     callback_data="nb_clients")],
        ]), parse_mode="Markdown"
    )

async def nb_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    if query.data == "nb_clients":
        clients = db.get_all_clients()
        lines = [f"👥 *База клієнтів:* {len(clients)} чол.\n"]
        for c in clients[:30]: lines.append(f"• {c['first_name']} @{c['username'] or '—'}")
        if len(clients) > 30: lines.append("\n_...і ще більше_")
        await query.edit_message_text("\n".join(lines),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="nb_back")]]))
    elif query.data == "nb_scheduled":
        posts = db.get_scheduled_posts()
        if not posts:
            await query.edit_message_text("📋 Немає запланованих постів.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="nb_back")]]))
            return
        lines = ["📋 *Заплановані пости:*\n"]
        for p in posts: lines.append(f"🕐 {p['scheduled_at']}\n📝 {p['text'][:60]}...\n")
        await query.edit_message_text("\n".join(lines),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="nb_back")]]))
    elif query.data == "nb_back":
        await query.edit_message_text("👑 *GlowRoom Admin*\n\nОбери дію 👇",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📝 Створити пост",     callback_data="nb_create_post")],
                [InlineKeyboardButton("📋 Заплановані пости", callback_data="nb_scheduled")],
                [InlineKeyboardButton("👥 База клієнтів",     callback_data="nb_clients")],
            ]), parse_mode="Markdown")

async def nb_create_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    context.user_data.clear()
    await query.edit_message_text("📝 *Створення посту*\n\nНапиши текст посту який побачать всі клієнти:\n\n_Для скасування: /cancel_", parse_mode="Markdown")
    return POST_TEXT

async def nb_post_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['post_text'] = update.message.text
    await update.message.reply_text("📸 Додай фото або пропусти:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🚫 Без фото", callback_data="nb_no_photo")]]))
    return POST_PHOTO

async def nb_post_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['post_photo'] = update.message.photo[-1].file_id
    return await nb_ask_schedule(update, context)

async def nb_no_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    context.user_data['post_photo'] = None
    await query.edit_message_text("⏰ *Коли відправити пост?*",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📤 Зараз",              callback_data="nb_now")],
            [InlineKeyboardButton("⏰ Запланувати на час", callback_data="nb_later")],
        ]), parse_mode="Markdown")
    return POST_SCHEDULE_TYPE

async def nb_ask_schedule(update, context):
    await update.message.reply_text("⏰ *Коли відправити пост?*",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📤 Зараз",              callback_data="nb_now")],
            [InlineKeyboardButton("⏰ Запланувати на час", callback_data="nb_later")],
        ]), parse_mode="Markdown")
    return POST_SCHEDULE_TYPE

async def nb_schedule_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    if query.data == "nb_now":
        context.user_data['scheduled_at'] = None
        return await nb_ask_delete_time(query, context)
    days_ua = {"Mon":"Пн","Tue":"Вт","Wed":"Ср","Thu":"Чт","Fri":"Пт","Sat":"Сб","Sun":"Нд"}
    keyboard = []
    for i in range(0, 14):
        day = datetime.now() + timedelta(days=i)
        ua = days_ua.get(day.strftime("%a"), "")
        keyboard.append([InlineKeyboardButton(f"{day.strftime('%d.%m')} ({ua})", callback_data=f"nbdate_{day.strftime('%Y-%m-%d')}")])
    await query.edit_message_text("📅 Обери дату розсилки:", reply_markup=InlineKeyboardMarkup(keyboard))
    return POST_SCHEDULE_DATE

async def nb_schedule_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    context.user_data['post_date'] = query.data.replace("nbdate_", "")
    times = ["09:00","10:00","11:00","12:00","13:00","14:00","15:00","16:00","17:00","18:00","19:00","20:00"]
    keyboard = []; row = []
    for t in times:
        row.append(InlineKeyboardButton(t, callback_data=f"nbtime_{t}"))
        if len(row) == 4: keyboard.append(row); row = []
    if row: keyboard.append(row)
    await query.edit_message_text("⏰ Обери час розсилки:", reply_markup=InlineKeyboardMarkup(keyboard))
    return POST_SCHEDULE_TIME

async def nb_schedule_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    t = query.data.replace("nbtime_", ""); d = context.user_data['post_date']
    context.user_data['scheduled_at'] = f"{d} {t}"
    return await nb_ask_delete_time(query, context)


async def nb_ask_delete_time(query, context):
    await query.edit_message_text(
        "🗑 Через скільки видалити пост у всіх?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("1 година",   callback_data="nbdel_1")],
            [InlineKeyboardButton("3 години",   callback_data="nbdel_3")],
            [InlineKeyboardButton("6 годин",    callback_data="nbdel_6")],
            [InlineKeyboardButton("12 годин",   callback_data="nbdel_12")],
            [InlineKeyboardButton("24 години",  callback_data="nbdel_24")],
            [InlineKeyboardButton("3 дні",      callback_data="nbdel_72")],
            [InlineKeyboardButton("🚫 Не видаляти", callback_data="nbdel_0")],
        ])
    )
    return POST_DELETE_TIME

async def nb_delete_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    hours = int(query.data.replace("nbdel_", ""))
    context.user_data['delete_after_hours'] = hours
    return await nb_preview(query, context)

async def nb_preview(query, context):
    d = context.user_data; scheduled = d.get('scheduled_at')
    delete_h = d.get('delete_after_hours', 0)
    delete_text = f"🗑 Видалити через {delete_h} год." if delete_h else "🗑 Не видаляти"
    preview = (f"Попередній перегляд:\n\n{d['post_text']}\n\n"
               f"{'📸 З фото' if d.get('post_photo') else 'Без фото'}\n"
               f"{'⏰ ' + scheduled if scheduled else '📤 Відправити зараз'}\n"
               f"{delete_text}\n\nПідтвердити?")
    await query.edit_message_text(preview,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Підтвердити", callback_data="nb_confirm_yes")],
            [InlineKeyboardButton("❌ Скасувати",   callback_data="nb_confirm_no")],
        ]))
    return POST_CONFIRM

async def nb_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    if query.data == "nb_confirm_no":
        await query.edit_message_text("Скасовано.")
        return ConversationHandler.END
    d = context.user_data; text = d['post_text']; photo = d.get('post_photo')
    scheduled_at = d.get('scheduled_at'); delete_h = d.get('delete_after_hours', 0)
    delete_txt = f", видалення через {delete_h} год." if delete_h else ""
    if scheduled_at:
        post_id = db.save_scheduled_post(text, photo, scheduled_at)
        dt = datetime.strptime(scheduled_at, "%Y-%m-%d %H:%M")
        global nb_scheduler
        nb_scheduler.add_job(nb_send_broadcast, 'date', run_date=dt, args=[text, photo, post_id, delete_h], id=f"post_{post_id}")
        await query.edit_message_text(f"✅ Пост заплановано на {scheduled_at}{delete_txt}!")
    else:
        await query.edit_message_text("📤 Розсилаю пост...")
        sent, failed, broadcast_id = await nb_send_broadcast(text, photo, delete_after_hours=delete_h)
        await context.bot.send_message(
            query.from_user.id,
            f"✅ Розсилка завершена!\nВідправлено: {sent} | Не доставлено: {failed}{delete_txt}",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🗑 Видалити у всіх зараз", callback_data=f"nb_delpost_{broadcast_id}")
            ]])
        )
    return ConversationHandler.END

async def nb_send_broadcast(text, photo, post_id=None, delete_after_hours=0):
    from telegram import Bot as TGBot
    main_bot = TGBot(token=BOT_TOKEN)
    clients = db.get_all_clients(); sent = failed = 0
    sent_messages = []
    for client in clients:
        try:
            if photo:
                msg = await main_bot.send_photo(client['user_id'], photo=photo, caption=text)
            else:
                msg = await main_bot.send_message(client['user_id'], text)
            sent_messages.append((client['user_id'], msg.message_id))
            sent += 1
        except Exception as e: logger.error(f"Broadcast error {client['user_id']}: {e}"); failed += 1
    if post_id: db.mark_post_sent(post_id)
    # Зберігаємо sent_messages в БД для можливості видалення
    broadcast_id = db.save_broadcast_messages(sent_messages)
    # Плануємо автовидалення якщо потрібно
    if delete_after_hours and delete_after_hours > 0 and sent_messages:
        delete_at = datetime.now() + timedelta(hours=delete_after_hours)
        global nb_scheduler
        nb_scheduler.add_job(
            nb_delete_messages, 'date', run_date=delete_at,
            args=[sent_messages], id=f"del_{post_id or int(datetime.now().timestamp())}"
        )
        logger.info(f"Заплановано видалення {len(sent_messages)} повідомлень через {delete_after_hours} год.")
    return sent, failed, broadcast_id


async def nb_delete_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    broadcast_id = int(query.data.replace("nb_delpost_", ""))
    sent_messages = db.get_broadcast_messages(broadcast_id)
    if not sent_messages:
        await query.edit_message_text("Повідомлення вже видалені або не знайдені.")
        return
    await query.edit_message_text("🗑 Видаляю повідомлення у всіх...")
    deleted = await nb_delete_messages(sent_messages)
    db.delete_broadcast_messages(broadcast_id)
    await context.bot.send_message(query.from_user.id, f"✅ Видалено {deleted} повідомлень.")

async def nb_delete_messages(sent_messages):
    from telegram import Bot as TGBot
    main_bot = TGBot(token=BOT_TOKEN)
    deleted = 0
    for user_id, message_id in sent_messages:
        try:
            await main_bot.delete_message(user_id, message_id)
            deleted += 1
        except Exception as e: logger.error(f"Delete error {user_id}/{message_id}: {e}")
    logger.info(f"Видалено {deleted} повідомлень з {len(sent_messages)}")
    return deleted

async def nb_cancel(update, context):
    await update.message.reply_text("Скасовано. Напиши /start")
    return ConversationHandler.END

# ══════════════════════════════════════════════════════
#  ЗАПУСК ОБОХ БОТІВ
# ══════════════════════════════════════════════════════

nb_scheduler = AsyncIOScheduler()

async def run():
    db.init_db()

    # Перший бот
    app1 = Application.builder().token(BOT_TOKEN).build()
    sched1 = AsyncIOScheduler()
    sched1.add_job(send_reminders_24h, 'cron', hour=10, minute=0, args=[app1])
    sched1.add_job(send_reminders_1h,  'cron', minute=0,           args=[app1])
    sched1.start()

    booking_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📅 Записатись$"), booking_start)],
        states={
            SELECT_CATEGORY: [CallbackQueryHandler(step_select_category, pattern="^cat_")],
            SELECT_SERVICE:  [CallbackQueryHandler(step_select_service, pattern="^(svc_|back_to_categories)$|^svc_|^back_to_categories")],
            CONFIRM_SERVICE: [CallbackQueryHandler(step_confirm_service, pattern="^(do_booking|back_to_cat_)")],
            SELECT_DATE:     [CallbackQueryHandler(step_select_date,    pattern="^date_")],
            SELECT_TIME:     [CallbackQueryHandler(step_select_time,    pattern="^time_")],
            ENTER_NAME:      [MessageHandler(filters.TEXT & ~filters.COMMAND, step_enter_name)],
            ENTER_PHONE:     [MessageHandler(filters.TEXT & ~filters.COMMAND, step_enter_phone)],
            CONFIRM_BOOKING: [CallbackQueryHandler(step_confirm_booking, pattern="^confirm_")],
        },
        fallbacks=[CommandHandler("cancel", cancel)], per_message=False,
    )
    app1.add_handler(CommandHandler("start", start))
    app1.add_handler(CommandHandler("admin", admin_panel))
    app1.add_handler(booking_conv)
    app1.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin_"))
    app1.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, handle_menu))

    # Другий бот
    app2 = Application.builder().token(NOTIFY_TOKEN).build()

    # Відновлюємо заплановані пости
    global nb_scheduler
    nb_scheduler.start()
    for p in db.get_scheduled_posts():
        try:
            dt = datetime.strptime(p['scheduled_at'], "%Y-%m-%d %H:%M")
            if dt > datetime.now():
                nb_scheduler.add_job(nb_send_broadcast, 'date', run_date=dt, args=[p['text'], p['photo'], p['id']], id=f"post_{p['id']}")
        except Exception as e: logger.error(f"Restore post: {e}")

    post_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(nb_create_post, pattern="^nb_create_post$")],
        states={
            POST_TEXT:          [MessageHandler(filters.TEXT & ~filters.COMMAND, nb_post_text)],
            POST_PHOTO:         [MessageHandler(filters.PHOTO, nb_post_photo), CallbackQueryHandler(nb_no_photo, pattern="^nb_no_photo$")],
            POST_SCHEDULE_TYPE: [CallbackQueryHandler(nb_schedule_type, pattern="^nb_(now|later)$")],
            POST_SCHEDULE_DATE: [CallbackQueryHandler(nb_schedule_date, pattern="^nbdate_")],
            POST_SCHEDULE_TIME: [CallbackQueryHandler(nb_schedule_time, pattern="^nbtime_")],
            POST_DELETE_TIME:   [CallbackQueryHandler(nb_delete_time, pattern="^nbdel_")],
            POST_CONFIRM:       [CallbackQueryHandler(nb_confirm, pattern="^nb_confirm_")],
        },
        fallbacks=[CommandHandler("cancel", nb_cancel)], per_message=False,
    )
    app2.add_handler(CommandHandler("start", nb_start))
    app2.add_handler(post_conv)
    app2.add_handler(CallbackQueryHandler(nb_delete_now, pattern="^nb_delpost_"))
    app2.add_handler(CallbackQueryHandler(nb_menu, pattern="^nb_(clients|scheduled|back)$"))

    logger.info("🚀 Запускаємо обидва боти!")
    await app1.initialize(); await app2.initialize()
    await app1.start();      await app2.start()
    await app1.updater.start_polling(drop_pending_updates=True)
    await app2.updater.start_polling(drop_pending_updates=True)
    logger.info("✅ Обидва боти працюють!")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(run())
