"""
Account commands: /start, /help, /whoami.

/start is the one command a chat that is not on the allowlist can reach, and
all it learns is its own Telegram ID, so it can ask an administrator for access.
"""

import logging

from telegram.constants import ParseMode

from botapp.actor import Actor
from botapp.auth import require_member, resolve_actor_fields
from botapp.db import run_db
from botapp.fm import formatters
from botapp.ui import category_keyboard, reply

logger = logging.getLogger(__name__)


def _welcome(chat_id):
    """Render inside the session; returns (text, allowed)."""
    fields = resolve_actor_fields(chat_id)
    if fields is None:
        return formatters.not_authorised_message(chat_id), False
    return formatters.welcome_message(Actor.from_dict(fields)), True


async def start_command(update, context):
    """/start and /help."""
    chat = update.effective_chat
    try:
        text, allowed = await run_db(_welcome, chat.id)
        await reply(update, text, category_keyboard() if allowed else None)
    except Exception as exc:
        logger.exception('/start failed')
        await reply(update, formatters.error_message(exc))


@require_member
async def whoami_command(update, context, user):
    """/whoami -- who this chat is speaking as."""
    await reply(update, formatters.whoami_message(user))


async def unknown_command(update, context):
    """
    Anything unrecognised, plus plain text.

    Without this a typo like /acvm produces total silence and the user assumes
    the bot is broken. Pointing back at /start is a better dead end.
    """
    if update.message is None:
        return
    await update.message.reply_text(
        "🤔 I didn't recognise that. Send /start to see what I can do."
    )
