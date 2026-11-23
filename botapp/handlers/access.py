"""
Access flow in Telegram: the request button, master control's approve/deny
buttons, and /access (pending requests and members, with revoke).

Callback data, all prefixed "acc:":
  acc:request        a person asks for access (anyone not yet approved)
  acc:ap:<id>        approve as end user         acc:ma:<id>  approve as master control
  acc:dn:<id>        deny                         acc:rv:<id>  revoke
  acc:rc:<id>        reconsider a denied/revoked person
"""

import datetime
import logging

from telegram.constants import ParseMode
from telegram.error import TelegramError

from core import access
from core.db import run_db
from core.fm import formatters
from core.models import BotMember
from botapp.auth import require_master, resolve_actor_fields
from botapp.ui import access_decision_keyboard, reply

logger = logging.getLogger(__name__)


# --- database work (runs inside run_db; returns plain data) ------------------
def _request(chat_id, username, name):
    state, member = access.request_access(chat_id, username, name)
    masters = []
    if state == 'requested':
        masters = [m.telegram_chat_id for m in access.masters()]
        if masters:
            BotMember.query.get(member['id']).masters_notified_at = datetime.datetime.utcnow()
            from core.db import db
            db.session.commit()
    return state, member, masters


def _decide(by_chat_id, action, member_id):
    fields = resolve_actor_fields(by_chat_id)
    if fields is None or fields['tier'] != 'master_control':
        raise access.AccessError('Only master control can do that')
    by = fields['member_id']
    if action == 'ap':
        m = access.approve(member_id, by, tier='end_user')
    elif action == 'ma':
        m = access.approve(member_id, by, tier='master_control')
    elif action == 'dn':
        m = access.deny(member_id, by)
    elif action == 'rv':
        m = access.revoke(member_id, by)
    elif action == 'rc':
        m = access.reconsider(member_id, by)
    else:
        raise access.AccessError('Unknown action')
    return m, fields['name']


def _mark_notified(member_id, status):
    from core.db import db
    BotMember.query.get(member_id).notified_status = status
    db.session.commit()


def _overview():
    pending = [access.serialize(m) for m in access.list_members('pending')]
    approved = [access.serialize(m) for m in access.list_members('approved')]
    return pending, approved


# --- handlers ----------------------------------------------------------------
async def request_callback(update, context):
    """Someone taps "Request access"."""
    chat = update.effective_chat
    user = update.effective_user
    try:
        state, member, masters = await run_db(
            _request, chat.id, user.username if user else None, user.full_name if user else None)
    except Exception as exc:
        logger.exception('access request failed')
        await reply(update, formatters.error_message(exc))
        return

    if state == 'requested':
        await reply(update, "📨 <b>Request sent.</b>\n\nMaster control has been told. "
                            "You will get a message here when it is decided. You do not need to ask again.")
        for chat_id in masters:
            try:
                await context.bot.send_message(
                    chat_id=chat_id, text=formatters.access_request_notice(member),
                    parse_mode=ParseMode.HTML, reply_markup=access_decision_keyboard(member['id']))
            except TelegramError:
                logger.warning('Could not tell master %s about request %s', chat_id, member['id'])
        if not masters:
            await context.bot.send_message(
                chat_id=chat.id, parse_mode=ParseMode.HTML,
                text="ℹ️ No master control is set up yet, so nobody can approve you. "
                     "Ask the person who runs this bot to add one.")
    else:
        await reply(update, formatters.access_state_message(state))


async def decision_callback(update, context, action, member_id):
    """A master control member taps Approve / Deny / Revoke / Reconsider."""
    chat = update.effective_chat
    try:
        member, decider = await run_db(_decide, chat.id, action, member_id)
    except access.AccessError as exc:
        await context.bot.send_message(chat_id=chat.id, text=f"⚠️ {exc}")
        return
    except Exception as exc:
        logger.exception('access decision failed')
        await reply(update, formatters.error_message(exc))
        return

    verb = {'ap': 'approved', 'ma': 'approved as master control', 'dn': 'denied',
            'rv': 'revoked', 'rc': 'put back to pending'}[action]
    await reply(update, f"{ {'ap': '✅', 'ma': '⭐', 'dn': '❌', 'rv': '🔒', 'rc': '↩️'}[action] } "
                        f"<b>{formatters._esc(member['name'])}</b> {verb} by {formatters._esc(decider)}.")

    if member['status'] in ('approved', 'denied', 'revoked'):
        try:
            await context.bot.send_message(
                chat_id=member['chat_id'], text=formatters.access_decision_notice(member['status']),
                parse_mode=ParseMode.HTML)
            await run_db(_mark_notified, member['id'], member['status'])
        except TelegramError:
            # Left for the poller, which retries until the requester has been told.
            logger.warning('Could not tell %s about their access decision', member['chat_id'])


@require_master
async def access_command(update, context, user):
    """/access -- pending requests with buttons, and who has access."""
    pending, approved = await run_db(_overview)
    if not pending and not approved:
        await reply(update, "Nobody has asked for access yet.")
        return
    lines = ["🛡 <b>Access</b>", ""]
    lines.append(f"<b>Pending requests:</b> {len(pending)}" if pending else "No pending requests.")
    lines += ["", "<b>Approved:</b>"]
    for m in approved:
        tier = "master control" if m['tier'] == 'master_control' else "end user"
        lines.append(f"   • {formatters._esc(m['name'])} — {tier}")
    await reply(update, "\n".join(lines))
    for m in pending:
        await update.effective_chat.send_message(
            formatters.access_request_notice(m), parse_mode=ParseMode.HTML,
            reply_markup=access_decision_keyboard(m['id']))
