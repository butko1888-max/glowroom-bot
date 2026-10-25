import os
import asyncio
import logging
import traceback
from datetime import datetime
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ConversationHandler,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

import database as db
import bot as b

BOT_TOKEN = os.getenv("BOT_TOKEN")
import threading, http.server
_ok = lambda s, *a: (s.send_response(200), s.end_headers(), s.wfile.write(b"ok"))
threading.Thread(target=http.server.HTTPServer(("0.0.0.0", int(os.getenv("PORT", "10000"))), type("H", (http.server.BaseHTTPRequestHandler,), {"do_GET": _ok, "do_HEAD": _ok, "log_message": lambda s, *a: None})).serve_forever, daemon=True).start()

async def _err_handler(update, context):
    logger.error("ERR: %s\n%s", context.error,
                 "".join(traceback.format_exception(
                     type(context.error), context.error, context.error.__traceback__)))


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
            b.SELECT_DATE:     [CallbackQueryHandler(b.step_select_date, pattern="^date_")],
            b.SELECT_TIME:     [CallbackQueryHandler(b.step_select_time, pattern="^time_")],
            b.ENTER_NAME:      [MessageHandler(filters.TEXT & ~filters.COMMAND, b.step_enter_name)],
            b.ENTER_PHONE:     [MessageHandler(filters.TEXT & ~filters.COMMAND, b.step_enter_phone)],
            b.CONFIRM_BOOKING: [CallbackQueryHandler(b.step_confirm_booking, pattern="^confirm_")],
        },
        fallbacks=[CommandHandler("cancel", b.cancel)], per_message=False,
    )

    app.add_handler(CommandHandler("start", b.start))
    app.add_handler(CommandHandler("admin", b.admin_panel))
    app.add_handler(booking_conv)
    app.add_handler(CallbackQueryHandler(b.admin_callback, pattern="^admin_"))
    app.add_handler(MessageHandler(filters.TEXT, b.handle_menu))
    return app


async def main():
    db.init_db()
    app1 = build_main_app()
    app1.add_error_handler(_err_handler)

    scheduler = AsyncIOScheduler()
    try:
        scheduler.add_job(b.send_reminders_24h, 'cron', hour=10, minute=0, args=[app1])
        scheduler.add_job(b.send_reminders_1h,  'cron', minute=0,           args=[app1])
    except Exception:
        logger.exception("scheduler setup failed")
    scheduler.start()

    logger.info("🚀 Starting main booking bot")

    await app1.initialize()
    await app1.start()
    await app1.updater.start_polling(drop_pending_updates=True)

    logger.info("✅ Main bot ready")
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
