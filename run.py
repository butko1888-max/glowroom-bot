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

import traceback as _tb
async def _err_handler(update, context):
    logger.error("HANDLER_ERROR: %s", context.error)
    logger.error("TRACEBACK:\n%s", "".join(_tb.format_exception(type(context.error), context.error, context.error.__traceback__)))

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
    app.add_handler(CommandHandler("start", nb.start))
    app.add_handler(CallbackQueryHandler(nb.nb_delete_now, pattern="^nb_delpost_"))
    app.add_handler(CallbackQueryHandler(nb.menu_handler, pattern="^menu_"))
    return app



async def main():
    db.init_db()

    app1 = build_main_app()
    # app2 = build_notify_app() (disabled, admin.py is new service)
    app2 = None
    app1.add_error_handler(_err_handler)
    app2.add_error_handler(_err_handler)

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
    # await app2.initialize() # disabled
    await app1.start()
    # await app2.start() # disabled
    await app1.updater.start_polling(drop_pending_updates=True)
    # app2 disabled

    logger.info("✅ Обидва боти працюють!")
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
