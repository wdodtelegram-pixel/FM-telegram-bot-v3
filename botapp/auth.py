"""
Who the bot will talk to.

Access is an allowlist of Telegram IDs (the `bot_members` table), managed from
the command line with `python -m botapp.admin`. There are no roles: everyone on
the list has full access. A chat that is not on the list gets exactly one
reply, which tells it its own Telegram ID so it can pass that to an
administrator, and sees no data.
"""

import functools
import logging

from telegram.constants import ParseMode

from botapp.actor import Actor
from botapp.db import run_db
from botapp.fm import formatters
from botapp.models import BotMember

logger = logging.getLogger(__name__)


def resolve_actor_fields(chat_id):
    """The member as a plain dict, or None if the chat is not allowed. Runs inside run_db()."""
    member = BotMember.query.filter_by(telegram_chat_id=chat_id).first()
    if member is None:
        return None
    return {'member_id': member.id, 'name': member.display_name, 'user_id': member.user_id}


def require_member(handler):
    """
    Refuse anything from a chat that is not on the allowlist.

        @require_member
        async def my_handler(update, context, user): ...

    `user` is a botapp.actor.Actor.
    """
    @functools.wraps(handler)
    async def wrapper(update, context, *args, **kwargs):
        chat = update.effective_chat
        if chat is None:
            return
        fields = await run_db(resolve_actor_fields, chat.id)
        if fields is None:
            await chat.send_message(formatters.not_authorised_message(chat.id),
                                    parse_mode=ParseMode.HTML)
            logger.info('Refused command from chat %s (not on the allowlist)', chat.id)
            return
        return await handler(update, context, Actor.from_dict(fields), *args, **kwargs)

    return wrapper
