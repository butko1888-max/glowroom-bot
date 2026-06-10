import asyncio
import logging
from datetime import datetime
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ConversationHandler
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

import database as db
import bot as b
import notify_bot as nb

BOT_TOKEN    = "8664438342:AAF1i1tHXRZXMsqMrPwXGtQsrjL1ZreEmuA"
NOTIFY_TOKEN = "8647746412:AAFD1ZRI9jbzr5GdgTkGCKzTI15UX9OvPM0"


def build_main_app():
    app = Application.builder().token(BOT_TOKEN).build()

    booking_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📅 Записатись$"), b.booking_start)],
        states={
            b.SELECT_CATEGORY: [CallbackQueryHandler(b.step_select_category, pattern="^cat_")],
            b.SELECT_SERVICE:  [
                CallbackQueryHandler(b.step_select_service, pattern="^svc_"),
                CallbackQueryHandler(b.step_select_service, pattern="^back_to_categories$"),
            ],
            b.CONFIRM_SERVICE: [
                CallbackQueryHandler(b.step_confirm_service, pattern="^do_booking$"),
                CallbackQueryHandler(b.step_confirm_service, pattern="^back_to_cat_"),
            ],
            b.SELECT_DATE:     [CallbackQueryHandler(b.step_select_date,    pattern="^date_")],
            b.SELECT_TIME:     [CallbackQueryHandler(b.step_select_time,    pattern="^time_")],
            b.ENTER_NAME:      [MessageHandler(filters.TEXT & ~filters.COMMAND, b.step_enter_name)],
            b.ENTER_PHONE:     [MessageHandler(filters.TEXT & ~filters.COMMAND, b.step_enter_phone)],
            b.CONFIRM_BOOKING: [CallbackQueryHandler(b.step_confirm_booking, pattern="^confirm_")],
        },
        fallbacks=[CommandHandler("cancel", b.cancel)],
        per_message=False,
    )
    app.add_handler(CommandHandler("start",  b.start))
    app.add_handler(CommandHandler("admin",  b.admin_panel))
    app.add_handler(booking_conv)
    app.add_handler(CallbackQueryHandler(b.admin_callback, pattern="^admin_"))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, b.handle_menu
    ))
    return app


def build_notify_app():
    app = Application.builder().token(NOTIFY_TOKEN).build()

    post_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(nb.create_post_start, pattern="^menu_create_post$")],
        states={
            nb.POST_TEXT:          [MessageHandler(filters.TEXT & ~filters.COMMAND, nb.post_get_text)],
            nb.POST_PHOTO:         [
                MessageHandler(filters.PHOTO, nb.post_get_photo),
                CallbackQueryHandler(nb.post_no_photo, pattern="^post_no_photo$"),
            ],
            nb.POST_SCHEDULE_TYPE: [CallbackQueryHandler(nb.post_schedule_type, pattern="^schedule_")],
            nb.POST_SCHEDULE_DATE: [CallbackQueryHandler(nb.post_schedule_date, pattern="^postdate_")],
            nb.POST_SCHEDULE_TIME: [CallbackQueryHandler(nb.post_schedule_time, pattern="^posttime_")],
            nb.POST_CONFIRM:       [CallbackQueryHandler(nb.post_confirm,        pattern="^post_confirm_")],
        },
        fallbacks=[CommandHandler("cancel", nb.cancel)],
        per_message=False,
    )
    app.add_handler(CommandHandler("start", nb.start))
    app.add_handler(post_conv)
    app.add_handler(CallbackQueryHandler(nb.menu_handler, pattern="^menu_"))
    return app


async def main():
    db.init_db()

    app1 = build_main_app()
    app2 = build_notify_app()

    # Планувальник нагадувань для першого бота
    scheduler1 = AsyncIOScheduler()
    scheduler1.add_job(b.send_reminders_24h, 'cron', hour=10, minute=0, args=[app1])
    scheduler1.add_job(b.send_reminders_1h,  'cron', minute=0,           args=[app1])
    scheduler1.start()

    # Планувальник постів для другого бота
    scheduler2 = AsyncIOScheduler()
    nb.scheduler = scheduler2
    posts = db.get_scheduled_posts()
    for p in posts:
        try:
            dt = datetime.strptime(p['scheduled_at'], "%Y-%m-%d %H:%M")
            if dt > datetime.now():
                scheduler2.add_job(
                    nb.send_broadcast, 'date', run_date=dt,
                    args=[app2, p['text'], p['photo'], p['id']],
                    id=f"post_{p['id']}"
                )
        except Exception as e:
            logger.error(f"Restore post error: {e}")
    scheduler2.start()

    logger.info("🚀 Запускаємо обидва боти!")

    await app1.initialize()
    await app2.initialize()
    await app1.start()
    await app2.start()
    await app1.updater.start_polling(drop_pending_updates=True)
    await app2.updater.start_polling(drop_pending_updates=True)

    logger.info("✅ Обидва боти працюють!")
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
