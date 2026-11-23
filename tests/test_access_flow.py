import asyncio
from unittest.mock import AsyncMock, MagicMock

from botapp import admin, notifications
from botapp.handlers import access as ah
from botapp.main import button_handler
from core import access
from core.models import BotMember


def chat_update(chat_id, data=None, name='Sam', username='sam'):
    u = MagicMock()
    u.effective_chat.id = chat_id
    u.effective_chat.send_message = AsyncMock()
    u.effective_user.username, u.effective_user.full_name = username, name
    if data is None:
        u.callback_query = None
        u.message.reply_text = AsyncMock()
    else:
        u.callback_query = MagicMock(); u.callback_query.data = data
        u.callback_query.answer = AsyncMock(); u.callback_query.edit_message_text = AsyncMock()
    return u


def ctx():
    c = MagicMock(); c.bot.send_message = AsyncMock(); c.args = []
    return c


def sent_to(c):
    return {call.kwargs['chat_id']: call.kwargs for call in c.bot.send_message.call_args_list}


def test_request_tells_every_master_with_decision_buttons_and_confirms_to_requester(session):
    admin.add_member(4001, 'Boss', tier='master_control')
    admin.add_member(4002, 'Boss2', tier='master_control')
    c, u = ctx(), chat_update(4100, 'acc:request')
    asyncio.run(button_handler(u, c))
    assert set(sent_to(c)) == {4001, 4002}
    kb = str(sent_to(c)[4001]['reply_markup'])
    assert 'acc:ap:' in kb and 'acc:ma:' in kb and 'acc:dn:' in kb
    assert access.state_for_chat(4100) == 'pending'
    assert BotMember.query.filter_by(telegram_chat_id=4100).one().masters_notified_at is not None
    assert 'Request sent' in u.callback_query.edit_message_text.call_args[0][0]


def test_asking_twice_does_not_notify_masters_again(session):
    admin.add_member(4003, 'Boss', tier='master_control')
    c1 = ctx(); asyncio.run(button_handler(chat_update(4101, 'acc:request'), c1))
    c2 = ctx(); asyncio.run(button_handler(chat_update(4101, 'acc:request'), c2))
    assert c1.bot.send_message.call_count == 1 and c2.bot.send_message.call_count == 0


def test_master_approves_and_requester_is_told_and_can_use_the_bot(session):
    admin.add_member(4004, 'Boss', tier='master_control')
    asyncio.run(button_handler(chat_update(4102, 'acc:request'), ctx()))
    mid = access.by_chat(4102).id
    c = ctx()
    asyncio.run(button_handler(chat_update(4004, f'acc:ap:{mid}'), c))
    m = access.by_chat(4102)
    assert m.status == 'approved' and m.tier == 'end_user' and m.notified_status == 'approved'
    assert 'approved' in sent_to(c)[4102]['text'].lower()


def test_approve_as_master_sets_the_tier(session):
    admin.add_member(4005, 'Boss', tier='master_control')
    asyncio.run(button_handler(chat_update(4103, 'acc:request'), ctx()))
    asyncio.run(button_handler(chat_update(4005, f'acc:ma:{access.by_chat(4103).id}'), ctx()))
    assert access.by_chat(4103).tier == 'master_control'


def test_an_end_user_tapping_approve_changes_nothing(session):
    admin.add_member(4006, 'Plain', tier='end_user')
    asyncio.run(button_handler(chat_update(4104, 'acc:request'), ctx()))
    mid = access.by_chat(4104).id
    c = ctx()
    asyncio.run(button_handler(chat_update(4006, f'acc:ap:{mid}'), c))
    assert access.by_chat(4104).status == 'pending'
    assert 'Only master control' in sent_to(c)[4006]['text']


def test_a_stranger_cannot_approve_themselves(session):
    asyncio.run(button_handler(chat_update(4105, 'acc:request'), ctx()))
    mid = access.by_chat(4105).id
    asyncio.run(button_handler(chat_update(4105, f'acc:ap:{mid}'), ctx()))
    assert access.by_chat(4105).status == 'pending'


def test_deny_is_remembered_and_the_person_is_told(session):
    admin.add_member(4007, 'Boss', tier='master_control')
    asyncio.run(button_handler(chat_update(4106, 'acc:request'), ctx()))
    c = ctx()
    asyncio.run(button_handler(chat_update(4007, f'acc:dn:{access.by_chat(4106).id}'), c))
    assert 'declined' in sent_to(c)[4106]['text']
    c2 = ctx(); u = chat_update(4106, 'acc:request')
    asyncio.run(button_handler(u, c2))
    assert c2.bot.send_message.call_count == 0 and access.state_for_chat(4106) == 'denied'


def test_access_command_is_master_only(session):
    admin.add_member(4008, 'Plain', tier='end_user')
    u = chat_update(4008)
    asyncio.run(ah.access_command(u, ctx()))
    assert 'Only master control' in u.effective_chat.send_message.call_args[0][0]


def test_access_command_lists_pending_with_buttons_for_master(session):
    admin.add_member(4009, 'Boss', tier='master_control')
    asyncio.run(button_handler(chat_update(4107, 'acc:request'), ctx()))
    u = chat_update(4009)
    asyncio.run(ah.access_command(u, ctx()))
    shown = str(u.effective_chat.send_message.call_args_list)
    assert 'Access request' in shown and 'acc:ap:' in shown


def test_poller_delivers_a_decision_made_elsewhere_exactly_once(session):
    boss = admin.add_member(4010, 'Boss', tier='master_control')
    asyncio.run(button_handler(chat_update(4108, 'acc:request'), ctx()))
    BotMember.query.filter_by(telegram_chat_id=4108)
    # the website approves (no Telegram message is sent by that path)
    access.approve(access.by_chat(4108).id, by_member_id=access.by_chat(4010).id)
    c = ctx()
    asyncio.run(notifications.poll_access(c))
    assert 'approved' in sent_to(c)[4108]['text'].lower()
    c2 = ctx(); asyncio.run(notifications.poll_access(c2))
    assert 4108 not in sent_to(c2)


def test_poller_tells_masters_about_a_pending_request_they_missed(session):
    # a request stored while no master existed
    BotMember.query.filter_by(tier='master_control').delete()
    session.flush()
    access.request_access(4109, 'late', 'Late')
    c0 = ctx(); asyncio.run(notifications.poll_access(c0))
    assert c0.bot.send_message.call_count == 0               # nobody to tell yet
    admin.add_member(4011, 'Boss', tier='master_control')
    c = ctx(); asyncio.run(notifications.poll_access(c))
    assert 4011 in sent_to(c) and 'Access request' in sent_to(c)[4011]['text']
