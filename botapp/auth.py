"""
Who the bot will talk to.

Access is a request/approve flow stored in `bot_members` (see core/access.py):
a person asks once, master control approves or denies in Telegram or the
website, and the decision is remembered. Two tiers: end_user (Telegram only)
and master_control (Telegram and website, and the person who decides).

A chat that is not approved sees no data. What it does see depends on where it
stands: a stranger is offered a "Request access" button, a pending request says
so, a denied or revoked chat is told to contact an administrator.
"""

import functools
import logging

from telegram.constants import ParseMode

from core import access
from core.actor import Actor
from core.db import run_db
from core.fm import formatters
from core.models import BotMember
from botapp.ui import request_access_keyboard

logger = logging.getLogger(__name__)


def resolve_actor_fields(chat_id):
    """The approved member as a plain dict, or None. Runs inside run_db()."""
    member = BotMember.query.filter_by(telegram_chat_id=chat_id).first()
    if member is None or member.status != 'approved':
        return None
    return {'member_id': member.id, 'name': member.display_name, 'user_id': member.user_id,
            'tier': member.tier}


def state_for_chat(chat_id):
    """'none' | 'pending' | 'approved' | 'denied' | 'revoked'. Runs inside run_db()."""
    return access.state_for_chat(chat_id)


async def _refuse(chat, state):
    await chat.send_message(
        formatters.access_state_message(state, chat.id), parse_mode=ParseMode.HTML,
        reply_markup=request_access_keyboard() if state == 'none' else None)
    logger.info('Refused command from chat %s (access state: %s)', chat.id, state)


def require_member(handler):
    """
    Refuse anything from a chat that is not approved.

        @require_member
        async def my_handler(update, context, user): ...

    `user` is a core.actor.Actor.
    """
    @functools.wraps(handler)
    async def wrapper(update, context, *args, **kwargs):
        chat = update.effective_chat
        if chat is None:
            return
        fields = await run_db(resolve_actor_fields, chat.id)
        if fields is None:
            await _refuse(chat, await run_db(state_for_chat, chat.id))
            return
        return await handler(update, context, Actor.from_dict(fields), *args, **kwargs)

    return wrapper


def require_master(handler):
    """Like require_member, and the person must also be master control."""
    @require_member
    @functools.wraps(handler)
    async def wrapper(update, context, user, *args, **kwargs):
        if not user.is_master:
            await update.effective_chat.send_message(
                formatters.master_only_message(), parse_mode=ParseMode.HTML)
            return
        return await handler(update, context, user, *args, **kwargs)

    return wrapper
