"""
Account commands: /start, /help, /whoami.

/start is the one command a chat that is not approved can reach. It offers a
"Request access" button (once) or says where the request stands.
"""

import logging

from telegram.constants import ParseMode

from core.actor import Actor
from botapp.auth import require_member, resolve_actor_fields, state_for_chat
from core.db import run_db
from core.fm import formatters
from botapp.ui import category_keyboard, reply, request_access_keyboard

logger = logging.getLogger(__name__)


def _welcome(chat_id):
    """Render inside the session; returns (text, keyboard_kind). kind: 'menu' | 'request' | None."""
    fields = resolve_actor_fields(chat_id)
    if fields is None:
        state = state_for_chat(chat_id)
        return formatters.access_state_message(state, chat_id), ('request' if state == 'none' else None)
    return formatters.welcome_message(Actor.from_dict(fields)), 'menu'


async def start_command(update, context):
    """/start and /help."""
    chat = update.effective_chat
    try:
        text, kind = await run_db(_welcome, chat.id)
        keyboard = {'menu': category_keyboard, 'request': request_access_keyboard}.get(kind)
        await reply(update, text, keyboard() if keyboard else None)
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
