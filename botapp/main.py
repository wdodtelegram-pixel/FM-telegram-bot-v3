"""
The Telegram front-end.

Run it as its own application, from Bot/:

    python -m botapp.main

It is independent of the web app: no Flask, no import from Backend/. It shares
only the PostgreSQL database (DATABASE_URL), mapping the tables it needs in
botapp/models.py. Access is an allowlist of Telegram IDs
(python -m botapp.admin), not a code from the website. `run_polling` owns its own event loop and blocks forever.

Structure carried over from the FM chatbot's bot.py -- the token pre-flight,
the generated per-trade handlers, the native command menu, the catch-all
registered last.
"""

import logging
import os
import sys
from functools import partial

from dotenv import load_dotenv
from telegram import BotCommand
from telegram.error import InvalidToken
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from botapp import config, notifications
from botapp import db as bot_db
from botapp.fm import catalog
from botapp.handlers import account, browse, defects

# httpx is silenced because it logs every single Telegram poll, which floods
# the log and hides anything useful.
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


def validate_token(token):
    """
    Check the token before building the Application, so a setup mistake gives
    four readable lines instead of an async traceback from inside the library.

    Only the shape is checked here. Whether Telegram actually recognises it is
    something only Telegram knows, which is what the InvalidToken catch below
    is for.
    """
    if not token:
        return False, (
            "TELEGRAM_BOT_TOKEN is not set.\n\n"
            "Copy Bot/.env.example to Bot/.env and add the token\n"
            "@BotFather gave you:\n\n"
            "  TELEGRAM_BOT_TOKEN=8123456789:AAHk...your-real-token\n\n"
            "Get one by messaging @BotFather on Telegram and sending /newbot."
        )

    prefix, _, suffix = token.partition(":")
    if not suffix:
        return False, (
            "The token is missing its colon.\n\n"
            "A real token looks like  <digits>:<letters and digits>\n"
            "Make sure you copied the ENTIRE string from @BotFather."
        )

    problems = []
    if not prefix.isdigit():
        problems.append(f"the part before the colon ('{prefix}') should be digits only")
    elif not 6 <= len(prefix) <= 16:
        problems.append(f"the part before the colon is {len(prefix)} digits, expected 6-16")
    if len(suffix) < 30:
        problems.append(f"the part after the colon is only {len(suffix)} chars, expected 30+")

    if problems:
        return False, (
            "The token is the wrong shape and Telegram will reject it.\n\n"
            + "\n".join(f"  - {p}" for p in problems)
            + "\n\nCommon causes:\n"
            "  - the token was cut short when copying\n"
            "  - a space or line break crept into the middle\n"
            "  - you copied the bot's username instead of its token"
        )

    return True, "Token format looks valid."


async def button_handler(update, context):
    """
    Decode taps on the inline keyboard.

    answer() must come first: it stops the loading spinner on the user's phone,
    which otherwise sits there for ~30 seconds and looks like a hang.
    """
    query = update.callback_query
    await query.answer()

    data = query.data or ''

    if data == 'refresh':
        await browse.refresh_command(update, context)
    elif data == 'pending':
        await browse.pending_command(update, context)
    elif data.startswith('cat:'):
        await browse.category_command(update, context, key=data.split(':', 1)[1])


async def error_handler(update, context):
    """
    Last line of defence. Anything not caught inside a handler lands here and
    is logged rather than killing the polling loop, so one bad row can never
    take the whole bot down.
    """
    logger.error("Unhandled exception", exc_info=context.error)


async def post_init(application: Application):
    """
    Register the command list with Telegram, which populates the blue Menu
    button next to the message box. Trade commands come from the catalog for
    the same reason everything else does.
    """
    commands = [
        BotCommand("start", "Show the welcome menu"),
        BotCommand("service", "Routine maintenance dashboard"),
    ]
    commands += [
        BotCommand(key, meta["blurb"]) for key, meta in catalog.CATEGORIES.items()
    ]
    commands += [
        BotCommand("calendar", "Maintenance agenda: today, week, month, overdue"),
        BotCommand("today", "What is scheduled today"),
        BotCommand("overdue", "Maintenance past its due date"),
        BotCommand("pending", "All outstanding maintenance"),
        BotCommand("myjobs", "Maintenance assigned to you"),
        BotCommand("defects", "Open building defects"),
        BotCommand("mydefects", "Defects assigned to you"),
        BotCommand("report", "Report a new defect"),
        BotCommand("whoami", "Show who you are signed in as"),
        BotCommand("refresh", "Reload the latest data"),
        BotCommand("help", "Show the command list"),
    ]

    await application.bot.set_my_commands(commands)
    logger.info("Bot commands registered with Telegram.")


def build_application(token):
    """
    Wire up every handler.

    Order matters: python-telegram-bot uses the first matching handler in each
    group, so the /report conversation is registered before the plain commands
    it shares message types with, and the catch-all goes last -- registered
    earlier it would swallow every real command.
    """
    application = ApplicationBuilder().token(token).post_init(post_init).build()

    # --- the /report conversation must come first ---------------------------
    application.add_handler(defects.build_report_conversation())

    # --- account -----------------------------------------------------------
    application.add_handler(CommandHandler(["start", "help"], account.start_command))
    application.add_handler(CommandHandler("whoami", account.whoami_command))

    # --- maintenance -------------------------------------------------------
    application.add_handler(CommandHandler("service", browse.service_command))
    application.add_handler(CommandHandler("pending", browse.pending_command))
    application.add_handler(CommandHandler("myjobs", browse.my_jobs_command))
    application.add_handler(CommandHandler("refresh", browse.refresh_command))
    application.add_handler(CommandHandler("calendar", browse.calendar_command))
    application.add_handler(CommandHandler("today", partial(browse.calendar_command, mode="today")))
    application.add_handler(CommandHandler("overdue", partial(browse.calendar_command, mode="overdue")))

    # One handler per trade, generated from the catalog. partial() freezes the
    # key so /acmv always calls category_command(..., key="acmv"); a plain loop
    # variable would leave every handler sharing the last value.
    for key in catalog.CATEGORIES:
        application.add_handler(
            CommandHandler(key, partial(browse.category_command, key=key))
        )

    # --- defects -----------------------------------------------------------
    application.add_handler(CommandHandler("defects", defects.defects_command))
    application.add_handler(CommandHandler("mydefects", defects.my_defects_command))

    # --- assignment alerts (polls the database; see botapp/notifications.py) --
    if application.job_queue is not None:
        application.job_queue.run_repeating(
            notifications.poll, interval=notifications.POLL_SECONDS, first=10)
    else:
        logger.warning("JobQueue unavailable (install python-telegram-bot[job-queue]); "
                       "assignment alerts are disabled.")

    # --- inline buttons ----------------------------------------------------
    application.add_handler(CallbackQueryHandler(button_handler))

    # --- catch-all (must be last) ------------------------------------------
    application.add_handler(MessageHandler(filters.COMMAND, account.unknown_command))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, account.unknown_command)
    )

    application.add_error_handler(error_handler)
    return application


def main():
    token = config.token()
    is_valid, message = validate_token(token)
    if not is_valid:
        print("\n" + "=" * 68)
        print("  CANNOT START - TOKEN PROBLEM")
        print("=" * 68)
        print(message)
        print("=" * 68 + "\n")
        raise SystemExit(1)

    try:
        bot_db.init_engine()
        # Fail with an instruction, not a traceback, if the schema is missing.
        from sqlalchemy import inspect
        tables = set(inspect(bot_db.get_engine()).get_table_names())
        missing = {'bot_members', 'defects', 'users'} - tables
        if missing:
            raise RuntimeError(
                f"missing table(s): {', '.join(sorted(missing))}.\n"
                "Run the web API's migrations first (flask db upgrade), then the bot's:\n"
                "  alembic -c migrations/alembic.ini upgrade head")
        try:
            n = notifications.baseline()
            if n:
                logger.info("First run: marked %d existing assignment(s) as already announced.", n)
        finally:
            bot_db.Session.remove()
    except Exception as exc:
        print("\n" + "=" * 68)
        print("  CANNOT START - DATABASE PROBLEM")
        print("=" * 68)
        print(exc)
        print("=" * 68 + "\n")
        raise SystemExit(1)

    application = build_application(token)

    logger.info("Building & FM bot starting (polling)...")

    try:
        application.run_polling(drop_pending_updates=True)  # offline backlog handling: see README, "Known limitations"
    except InvalidToken:
        print("\n" + "=" * 68)
        print("  TELEGRAM REJECTED YOUR TOKEN")
        print("=" * 68)
        print(
            "The token is correctly formatted, but Telegram does not recognise it.\n\n"
            "Likely causes:\n"
            "  - the token was revoked (/revoke in @BotFather issues a new one)\n"
            "  - the bot was deleted with /deletebot\n"
            "  - one character is wrong - re-copy the whole string\n\n"
            "Send /mybots to @BotFather, pick your bot, then 'API Token'."
        )
        print("=" * 68 + "\n")
        raise SystemExit(1)
    except KeyboardInterrupt:
        # Ctrl+C is a normal way to stop the bot, not a crash.
        logger.info("Bot stopped by user.")


if __name__ == '__main__':
    sys.exit(main() or 0)
