import asyncio

from botapp import notifications as n
from botapp.models import BotMember, BotNotificationLog, Defect


def _member(session, user, chat=5001):
    m = BotMember(telegram_chat_id=chat, display_name='Tina', user_id=user.id)
    session.add(m); session.flush()
    return m


def _assigned(session, world):
    d = Defect(title='Leak', description='Roof', priority='high', building_id=world['building'].id,
               reporter_id=world['csr'].id, assigned_technician_id=world['tech'].id)
    session.add(d); session.flush()
    return d


def test_alert_goes_to_the_mapped_member_once(session, world):
    _member(session, world['tech'])
    d = _assigned(session, world)
    pending = [p for p in n.collect_pending() if p['defect_id'] == d.id]
    assert len(pending) == 1 and pending[0]['chat_id'] == 5001 and 'Leak' in pending[0]['text']
    n.record_result(d.id, world['tech'].id, True)
    assert not [p for p in n.collect_pending() if p['defect_id'] == d.id]


def test_unmapped_technician_gets_no_alert(session, world):
    d = _assigned(session, world)
    assert not [p for p in n.collect_pending() if p['defect_id'] == d.id]


def test_failures_retry_then_give_up(session, world):
    _member(session, world['tech'])
    d = _assigned(session, world)
    for _ in range(n.MAX_ATTEMPTS):
        assert [p for p in n.collect_pending() if p['defect_id'] == d.id]
        n.record_result(d.id, world['tech'].id, False, 'boom')
    assert not [p for p in n.collect_pending() if p['defect_id'] == d.id]


def test_blocked_bot_is_not_retried(session, world):
    _member(session, world['tech'])
    d = _assigned(session, world)
    n.record_result(d.id, world['tech'].id, False, 'Forbidden', permanent=True)
    assert not [p for p in n.collect_pending() if p['defect_id'] == d.id]


def test_baseline_only_when_log_is_empty(session, world):
    BotNotificationLog.query.delete(); session.flush()
    _assigned(session, world)
    assert n.baseline() >= 1
    assert n.baseline() == 0
