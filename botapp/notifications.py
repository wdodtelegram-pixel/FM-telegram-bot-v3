"""
Assignment alerts, delivered by the bot itself.

When this lived in the web API it posted to Telegram at the moment of
assignment, best-effort, with no retry: a blip meant a lost alert, and the API
needed the bot token. Now the bot polls the database for defects assigned to a
member who is mapped to a web account, sends each alert once, and records the
outcome in bot_notification_log. The API never touches Telegram.

Failure handling: a transient error is retried on later cycles up to
MAX_ATTEMPTS; if the member blocked the bot (Forbidden) it is not retried.
"""

import datetime
import logging

from telegram.constants import ParseMode
from telegram.error import Forbidden

import datetime as _dt

from sqlalchemy import or_

from core import access
from core.db import db, run_db
from core.fm import formatters
from core.models import BotMember, BotNotificationLog, Defect

logger = logging.getLogger(__name__)

POLL_SECONDS = 30
MAX_ATTEMPTS = 5
BATCH = 20


def _candidates():
    """(defect, member) pairs with no delivered/abandoned log row yet."""
    rows = (
        db.session.query(Defect, BotMember)
        .join(BotMember, BotMember.user_id == Defect.assigned_technician_id)
        .outerjoin(BotNotificationLog, (BotNotificationLog.kind == 'defect')
                   & (BotNotificationLog.ref_id == Defect.id)
                   & (BotNotificationLog.user_id == Defect.assigned_technician_id))
        .filter(Defect.deleted_at.is_(None),
                Defect.status != 'Completed',
                (BotNotificationLog.id.is_(None))
                | ((BotNotificationLog.delivered_at.is_(None))
                   & (BotNotificationLog.attempts < MAX_ATTEMPTS)))
        .order_by(Defect.id)
        .limit(BATCH)
        .all()
    )
    return rows


def collect_pending():
    """Render the alerts that are due. Plain dicts out: the session closes after."""
    out = []
    for defect, member in _candidates():
        out.append({
            'defect_id': defect.id,
            'user_id': defect.assigned_technician_id,
            'chat_id': member.telegram_chat_id,
            'text': formatters.defect_assigned_message(defect),
        })
    return out


def record_result(defect_id, user_id, ok, error=None, permanent=False):
    log = BotNotificationLog.query.filter_by(
        kind='defect', ref_id=defect_id, user_id=user_id).first()
    if log is None:
        log = BotNotificationLog(kind='defect', ref_id=defect_id, user_id=user_id, attempts=0)
        db.session.add(log)
    log.attempts += 1
    if ok:
        log.delivered_at = datetime.datetime.utcnow()
        log.last_error = None
    else:
        log.last_error = (error or '')[:500]
        if permanent:
            log.attempts = MAX_ATTEMPTS
    db.session.commit()


def baseline():
    """
    On the very first run, mark every existing assignment as already handled.

    Otherwise switching to this bot would re-announce every defect that was
    assigned long ago. Does nothing once the log has any rows.
    """
    if BotNotificationLog.query.first() is not None:
        return 0
    n = 0
    for defect in Defect.query.filter(Defect.assigned_technician_id.isnot(None)).all():
        db.session.add(BotNotificationLog(
            kind='defect', ref_id=defect.id, user_id=defect.assigned_technician_id,
            attempts=0, delivered_at=datetime.datetime.utcnow(), last_error='baseline'))
        n += 1
    db.session.commit()
    return n


async def poll(context):
    """JobQueue callback."""
    try:
        pending = await run_db(collect_pending)
    except Exception:
        logger.exception('Could not look for assignment alerts')
        return

    for item in pending:
        try:
            await context.bot.send_message(
                chat_id=item['chat_id'], text=item['text'], parse_mode=ParseMode.HTML)
            await run_db(record_result, item['defect_id'], item['user_id'], True)
        except Forbidden as exc:
            await run_db(record_result, item['defect_id'], item['user_id'], False, str(exc), True)
        except Exception as exc:
            logger.warning('Alert for defect %s failed: %s', item['defect_id'], exc)
            await run_db(record_result, item['defect_id'], item['user_id'], False, str(exc))


# ---------------------------------------------------------------------------
# Access notices
# ---------------------------------------------------------------------------
def collect_access_notices():
    """
    Decisions the requester has not been told about (typically made in the
    website) and pending requests master control has not been told about.
    Plain dicts out: the session closes after this returns.
    """
    from botapp.ui import access_decision_keyboard    # keyboards are built by the sender
    out = []
    decided = (BotMember.query
               .filter(BotMember.status.in_(('approved', 'denied', 'revoked')),
                       or_(BotMember.notified_status.is_(None),
                           BotMember.notified_status != BotMember.status))
               .limit(BATCH).all())
    for m in decided:
        out.append({'kind': 'decision', 'member_id': m.id, 'chats': [m.telegram_chat_id],
                    'status': m.status, 'text': formatters.access_decision_notice(m.status)})

    masters = [x.telegram_chat_id for x in access.masters()]
    if masters:
        pending = (BotMember.query.filter_by(status='pending', masters_notified_at=None)
                   .limit(BATCH).all())
        for m in pending:
            out.append({'kind': 'request', 'member_id': m.id, 'chats': masters, 'status': 'pending',
                        'text': formatters.access_request_notice(access.serialize(m))})
    return out


def mark_access_notified(kind, member_id, status):
    m = BotMember.query.get(member_id)
    if m is None:
        return
    if kind == 'decision':
        m.notified_status = status
    else:
        m.masters_notified_at = _dt.datetime.utcnow()
    db.session.commit()


async def poll_access(context):
    """JobQueue callback: deliver access notices the interactive path did not."""
    from botapp.ui import access_decision_keyboard
    try:
        notices = await run_db(collect_access_notices)
    except Exception:
        logger.exception('Could not look for access notices')
        return

    for n in notices:
        delivered = False
        for chat_id in n['chats']:
            try:
                await context.bot.send_message(
                    chat_id=chat_id, text=n['text'], parse_mode=ParseMode.HTML,
                    reply_markup=access_decision_keyboard(n['member_id']) if n['kind'] == 'request' else None)
                delivered = True
            except Forbidden:
                delivered = True        # they blocked the bot; retrying cannot help
            except Exception as exc:
                logger.warning('Access notice for member %s failed: %s', n['member_id'], exc)
        if delivered:
            await run_db(mark_access_notified, n['kind'], n['member_id'], n['status'])
