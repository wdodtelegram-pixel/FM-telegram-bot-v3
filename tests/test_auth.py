import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from botapp import admin, auth
from botapp.handlers import account
from botapp.models import BotMember


def test_listed_chat_resolves_and_stranger_does_not(session):
    admin.add_member(2001, 'Pat')
    assert auth.resolve_actor_fields(2001)['name'] == 'Pat'
    assert auth.resolve_actor_fields(2002) is None


def test_remove_revokes_access(session):
    admin.add_member(2003, 'Sam')
    assert admin.remove_member(2003)
    assert auth.resolve_actor_fields(2003) is None
    assert not admin.remove_member(2003)


def test_duplicate_add_is_refused(session):
    admin.add_member(2004, 'A')
    with pytest.raises(admin.AdminError):
        admin.add_member(2004, 'B')


def test_add_with_unknown_web_user_is_refused(session):
    with pytest.raises(admin.AdminError):
        admin.add_member(2005, 'A', web_user=999999)


def test_link_user_maps_and_clears(session, world):
    admin.add_member(2006, 'Tina')
    assert auth.resolve_actor_fields(2006)['user_id'] is None
    admin.link_user(2006, world['tech'].id)
    assert auth.resolve_actor_fields(2006)['user_id'] == world['tech'].id
    admin.link_user(2006, None)
    assert auth.resolve_actor_fields(2006)['user_id'] is None
    with pytest.raises(admin.AdminError):
        admin.link_user(2007, world['tech'].id)          # not on the list


def test_import_links_adds_previously_linked_web_users(session, world):
    from sqlalchemy import text
    session.execute(text("UPDATE users SET telegram_chat_id = 2008 WHERE id = :i"),
                    {'i': world['tech'].id})
    assert admin.import_links() >= 1
    assert auth.resolve_actor_fields(2008)['user_id'] == world['tech'].id
    assert admin.import_links() == 0                     # idempotent


def _update(chat_id):
    u = MagicMock()
    u.callback_query = None
    u.effective_chat.id = chat_id
    u.effective_chat.send_message = AsyncMock()
    u.message.reply_text = AsyncMock()
    return u


def test_stranger_gets_only_their_id_and_no_data(session):
    seen = []

    @auth.require_member
    async def secret(update, context, user):
        seen.append(user)

    u = _update(2009)
    asyncio.run(secret(u, MagicMock()))
    assert not seen
    text = u.effective_chat.send_message.call_args[0][0]
    assert '2009' in text and 'not authorised' in text


def test_member_reaches_the_handler_with_an_actor(session):
    admin.add_member(2010, 'Ann')
    seen = []

    @auth.require_member
    async def ok(update, context, user):
        seen.append(user)

    asyncio.run(ok(_update(2010), MagicMock()))
    assert seen and seen[0].name == 'Ann' and seen[0].user_id is None


def test_start_for_a_stranger_shows_their_id_not_the_menu(session):
    u = _update(2011)
    asyncio.run(account.start_command(u, MagicMock()))
    text = u.effective_chat.send_message.call_args[0][0]
    assert '2011' in text and '/service' not in text
