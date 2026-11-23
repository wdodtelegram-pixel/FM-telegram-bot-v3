"""
The guided flows: Event query and Defect reporting.

"Guided" means the bot leads. Every step is a prompt with an example and
buttons, the user answers, and nobody needs to know a command. Each step has
Back and Cancel; /cancel works anywhere.

Defect reporting is match-first, create-last:
  when -> equipment type -> location -> what is the issue
       -> the bot searches the SCHEDULED and UNSCHEDULED stores for the closest
          records and asks "Is this it?" for each
       -> a yes records the report against that scheduled item, or adds it to
          that earlier report; "none of these" creates a fresh report
          (specific equipment, priority, optional photo).
Event query: when -> the scheduled items in that period, grouped by type.

Callback data: rp:* (report), ev:* (event query), menu:* (entry buttons).
"""

import base64
import datetime
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from botapp.auth import require_member
from botapp.ui import reply
from core import config, equipment, similarity
from core.db import run_db
from core.fm import catalog, formatters
from core.services import maintenance_service, report_service
from core.when import parse_range, parse_when, quick_range

logger = logging.getLogger(__name__)

MAX_PHOTO_BYTES = 400_000          # largest Telegram size under this, else the smallest
CONVERSATION_TIMEOUT = 30 * 60     # an abandoned flow is dropped, with a message

# --- report states -----------------------------------------------------------
WHEN, TYPE, LOCATION, ISSUE, MATCH, SPECIFIC, PRIORITY, PHOTO, CONFIRM = range(9)
# --- event query states ------------------------------------------------------
EV_WHEN, EV_TYPED = range(10, 12)

_BACK = {TYPE: WHEN, LOCATION: TYPE, ISSUE: LOCATION, MATCH: ISSUE,
         SPECIFIC: ISSUE, PRIORITY: SPECIFIC, PHOTO: PRIORITY}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def _nav(back=True):
    row = []
    if back:
        row.append(InlineKeyboardButton("⬅️ Back", callback_data="rp:back"))
    row.append(InlineKeyboardButton("✖️ Cancel", callback_data="rp:cancel"))
    return row


def _kb(rows, back=True):
    return InlineKeyboardMarkup(rows + [_nav(back)])


def _chunk(buttons, n=2):
    return [buttons[i:i + n] for i in range(0, len(buttons), n)]


def _data(context):
    return context.user_data.setdefault('rp', {})


# ---------------------------------------------------------------------------
# Event query
# ---------------------------------------------------------------------------
def _ev_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Today", callback_data="ev:today"),
         InlineKeyboardButton("➡️ Tomorrow", callback_data="ev:tomorrow")],
        [InlineKeyboardButton("🗓 Next 7 days", callback_data="ev:week"),
         InlineKeyboardButton("✏️ Pick a date", callback_data="ev:pick")],
        [InlineKeyboardButton("✖️ Cancel", callback_data="ev:cancel")],
    ])


def _after_query_keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("📅 New query", callback_data="menu:events"),
        InlineKeyboardButton("🛠 Report a defect", callback_data="menu:report")]])


@require_member
async def events_entry(update, context, user):
    await reply(update,
                "📅 <b>Event query</b>\n\nWhen do you want to look?\n"
                "Tap a quick option, or choose <b>Pick a date</b> to type one.",
                _ev_keyboard())
    return EV_WHEN


def _render_events(title, start, end):
    return formatters.events_message(title, maintenance_service.events_between(start, end))


async def _show_events(update, title, start, end):
    text = await run_db(_render_events, title, start, end)
    await reply(update, text, _after_query_keyboard())
    return ConversationHandler.END


async def events_quick(update, context):
    choice = update.callback_query.data.split(':', 1)[1]
    today = config.today()
    start, end = quick_range(choice, today)
    title = {'today': f"Today · {today:%a %d %b %Y}",
             'tomorrow': f"Tomorrow · {start:%a %d %b %Y}",
             'week': f"Next 7 days · {start:%d %b} – {end:%d %b %Y}"}[choice]
    return await _show_events(update, title, start, end)


async def events_pick(update, context):
    await reply(update,
                "✏️ <b>Which date?</b>\n\nType a day, or a range:\n"
                "<code>25 Nov</code>   <code>25/11/2026</code>   <code>25 Nov - 30 Nov</code>",
                InlineKeyboardMarkup([[InlineKeyboardButton("✖️ Cancel", callback_data="ev:cancel")]]))
    return EV_TYPED


async def events_typed(update, context):
    parsed = parse_range(update.message.text, config.today())
    if parsed is None:
        await reply(update, "🤔 I could not read that date.\n\nTry <code>25 Nov</code>, "
                            "<code>25/11/2026</code> or <code>25 Nov - 30 Nov</code>.",
                    InlineKeyboardMarkup([[InlineKeyboardButton("✖️ Cancel", callback_data="ev:cancel")]]))
        return EV_TYPED
    start, end = parsed
    title = (f"{start:%a %d %b %Y}" if start.date() == end.date()
             else f"{start:%d %b} – {end:%d %b %Y}")
    return await _show_events(update, title, start, end)


async def events_cancel(update, context):
    await reply(update, "❎ Cancelled.", _after_query_keyboard())
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Defect reporting: prompts
# ---------------------------------------------------------------------------
async def _prompt_when(update, context):
    await reply(update,
                "🛠 <b>Report a defect</b>  (step 1 of 4)\n\n"
                "🕒 <b>When did it happen?</b>\n"
                "Tap an option, or type a date and time, e.g. <code>25 Nov 14:30</code> or <code>14:30</code>.",
                _kb([[InlineKeyboardButton("⚡ Just now", callback_data="rp:when:now"),
                      InlineKeyboardButton("1 hour ago", callback_data="rp:when:h1")],
                     [InlineKeyboardButton("3 hours ago", callback_data="rp:when:h3"),
                      InlineKeyboardButton("Yesterday", callback_data="rp:when:yday")]], back=False))
    return WHEN


async def _prompt_type(update, context):
    buttons = [InlineKeyboardButton(f"{meta['emoji']} {meta['name']}", callback_data=f"rp:type:{key}")
               for key, meta in catalog.CATEGORIES.items()]
    await reply(update,
                "🛠 <b>Report a defect</b>  (step 2 of 4)\n\n🔧 <b>Which equipment type?</b>",
                _kb(_chunk(buttons)))
    return TYPE


async def _prompt_location(update, context):
    await reply(update,
                "🛠 <b>Report a defect</b>  (step 3 of 4)\n\n📍 <b>Where is it?</b>\n"
                "Type the location, e.g. <code>Level 3 Plant Room</code> or <code>Tower A lift lobby</code>.",
                _kb([]))
    return LOCATION


async def _prompt_issue(update, context):
    await reply(update,
                "🛠 <b>Report a defect</b>  (step 4 of 4)\n\n📝 <b>What is the issue?</b>\n"
                "Name the equipment and what is wrong, e.g. "
                "<code>Chiller 2 making a loud grinding noise</code>.",
                _kb([]))
    return ISSUE


async def _prompt_specific(update, context):
    await reply(update,
                "🆕 <b>New report</b>\n\n⚙️ <b>Which specific equipment?</b> (optional)\n"
                "e.g. <code>Cooling tower 2</code> or <code>Escalator E4</code>.",
                _kb([[InlineKeyboardButton("⏭ Skip", callback_data="rp:skip")]]))
    return SPECIFIC


async def _prompt_priority(update, context):
    await reply(update, "🆕 <b>New report</b>\n\n🚦 <b>How urgent is it?</b>",
                _kb([[InlineKeyboardButton("🔹 Low", callback_data="rp:pri:low"),
                      InlineKeyboardButton("🔸 Medium", callback_data="rp:pri:medium"),
                      InlineKeyboardButton("🔺 High", callback_data="rp:pri:high")]]))
    return PRIORITY


async def _prompt_photo(update, context):
    await reply(update, "🆕 <b>New report</b>\n\n📷 <b>Send a photo</b> if you have one.",
                _kb([[InlineKeyboardButton("⏭ Skip", callback_data="rp:skip")]]))
    return PHOTO


async def _prompt_confirm(update, context):
    d = _data(context)
    await reply(update, formatters.report_summary_message(d),
                _kb([[InlineKeyboardButton("✅ Submit", callback_data="rp:ok")]]))
    return CONFIRM


_PROMPTS = {WHEN: _prompt_when, TYPE: _prompt_type, LOCATION: _prompt_location, ISSUE: _prompt_issue,
            SPECIFIC: _prompt_specific, PRIORITY: _prompt_priority, PHOTO: _prompt_photo,
            CONFIRM: _prompt_confirm}


# ---------------------------------------------------------------------------
# Defect reporting: handlers
# ---------------------------------------------------------------------------
@require_member
async def report_entry(update, context, user):
    context.user_data['rp'] = {'actor': user}
    return await _prompt_when(update, context)


async def report_when_button(update, context):
    now = config.now()
    option = update.callback_query.data.split(':')[2]
    when = {'now': now, 'h1': now - datetime.timedelta(hours=1),
            'h3': now - datetime.timedelta(hours=3), 'yday': now - datetime.timedelta(days=1)}[option]
    _data(context)['when'] = when
    return await _prompt_type(update, context)


async def report_when_text(update, context):
    when = parse_when(update.message.text, config.now())
    if when is None:
        await reply(update, "🤔 I could not read that.\n\nTry <code>25 Nov 14:30</code>, "
                            "<code>25/11 09:00</code>, <code>14:30</code> or <code>yesterday 16:00</code>.",
                    _kb([[InlineKeyboardButton("⚡ Just now", callback_data="rp:when:now")]], back=False))
        return WHEN
    if when > config.now() + report_service.MAX_FUTURE:
        await reply(update, "That time is in the future. When did it actually happen?",
                    _kb([[InlineKeyboardButton("⚡ Just now", callback_data="rp:when:now")]], back=False))
        return WHEN
    _data(context)['when'] = when
    return await _prompt_type(update, context)


async def report_type(update, context):
    key = update.callback_query.data.split(':')[2]
    meta = catalog.CATEGORIES.get(key)
    if meta is None:
        return await _prompt_type(update, context)
    etype_id = await run_db(_type_id, key)
    d = _data(context)
    d.update(type_key=key, type_name=f"{meta['emoji']} {meta['name']}", type_id=etype_id)
    return await _prompt_location(update, context)


def _type_id(key):
    t = equipment.get_by_key_or_name(key)
    return t.id if t else None


async def report_location(update, context):
    text = (update.message.text or '').strip()
    if len(text) < report_service.MIN_LOCATION_CHARS:
        await reply(update, "Please tell me where it is, e.g. <code>Level 3 Plant Room</code>.", _kb([]))
        return LOCATION
    _data(context)['location'] = text
    return await _prompt_issue(update, context)


def _find_matches(d):
    found = report_service.suggest(d['type_id'], d['when'], d['location'], d['issue'])
    return [{'store': m.store, 'id': m.record_id, 'label': m.label, 'score': m.score, 'reasons': m.reasons}
            for m in similarity.rank(found)]


async def report_issue(update, context):
    text = (update.message.text or '').strip()
    if len(text) < report_service.MIN_ISSUE_CHARS:
        await reply(update, "Please give a bit more detail so it can be matched and fixed.", _kb([]))
        return ISSUE
    d = _data(context)
    d['issue'] = text
    try:
        d['matches'] = await run_db(_find_matches, d)
    except report_service.ReportError as exc:
        await reply(update, f"⚠️ {formatters._esc(str(exc))}", _kb([]))
        return ISSUE
    d['mi'] = 0
    if not d['matches']:
        d['choice'] = ('new', None)
        await reply(update, "🔎 I looked through the scheduled items and earlier reports and found "
                            "<b>nothing similar</b>. Let's create a fresh report.")
        return await _prompt_specific(update, context)
    return await _show_match(update, context)


async def _show_match(update, context):
    d = _data(context)
    m = d['matches'][d['mi']]
    rows = [[InlineKeyboardButton("✅ Yes, this one", callback_data="rp:m:yes")]]
    if d['mi'] + 1 < len(d['matches']):
        rows.append([InlineKeyboardButton("➡️ Next match", callback_data="rp:m:next")])
    rows.append([InlineKeyboardButton("🆕 None of these", callback_data="rp:m:none")])
    await reply(update, formatters.match_message(m, d['mi'] + 1, len(d['matches'])), _kb(rows))
    return MATCH


async def report_match(update, context):
    d = _data(context)
    action = update.callback_query.data.split(':')[2]
    if action == 'next':
        d['mi'] += 1
        return await _show_match(update, context)
    if action == 'none':
        d['choice'] = ('new', None)
        return await _prompt_specific(update, context)
    m = d['matches'][d['mi']]
    d['choice'] = (m['store'], m['id'])
    d['choice_label'] = m['label']
    return await _prompt_confirm(update, context)


async def report_specific_text(update, context):
    _data(context)['specific_equipment'] = (update.message.text or '').strip() or None
    return await _prompt_priority(update, context)


async def report_skip(update, context):
    """The Skip button on the specific-equipment and photo steps."""
    d = _data(context)
    if d.get('_step') == PHOTO:
        return await _prompt_confirm(update, context)
    d['specific_equipment'] = None
    return await _prompt_priority(update, context)


async def report_priority(update, context):
    _data(context)['priority'] = update.callback_query.data.split(':')[2]
    return await _prompt_photo(update, context)


async def report_photo(update, context):
    sizes = update.message.photo or []
    if not sizes:
        await reply(update, "That did not come through as a photo. Send one, or tap Skip.",
                    _kb([[InlineKeyboardButton("⏭ Skip", callback_data="rp:skip")]]))
        return PHOTO
    chosen = next((s for s in reversed(sizes) if (s.file_size or 0) <= MAX_PHOTO_BYTES), sizes[0])
    try:
        tg_file = await chosen.get_file()
        raw = bytes(await tg_file.download_as_bytearray())
    except Exception:
        logger.exception('photo download failed')
        await reply(update, "⚠️ I could not download that photo. Send another, or tap Skip.",
                    _kb([[InlineKeyboardButton("⏭ Skip", callback_data="rp:skip")]]))
        return PHOTO
    _data(context)['image'] = 'data:image/jpeg;base64,' + base64.b64encode(raw).decode('ascii')
    return await _prompt_confirm(update, context)


def _record(d):
    return report_service.record_report(
        d['actor'], d['type_id'], d['when'], d['location'], d['issue'], choice=d['choice'],
        specific_equipment=d.get('specific_equipment'), priority=d.get('priority', 'medium'),
        image=d.get('image'))


async def report_confirm(update, context):
    d = _data(context)
    try:
        result = await run_db(_record, d)
    except report_service.ReportError as exc:
        await reply(update, f"⚠️ {formatters._esc(str(exc))}\n\nStart again with /report.")
    except Exception as exc:
        logger.exception('report submit failed')
        await reply(update, formatters.error_message(exc))
    else:
        await reply(update, formatters.report_result_message(result), _after_query_keyboard())
    context.user_data.pop('rp', None)
    return ConversationHandler.END


async def report_back(update, context):
    d = _data(context)
    if not d.get('actor'):
        return ConversationHandler.END
    step = d.get('_step')
    if step == CONFIRM:
        target = PHOTO if d.get('choice', ('new',))[0] == 'new' else MATCH
    else:
        target = _BACK.get(step, WHEN)
    if target == MATCH:
        return await _show_match(update, context)
    return await _PROMPTS[target](update, context)


async def report_cancel(update, context):
    context.user_data.pop('rp', None)
    await reply(update, "❎ Cancelled. Nothing was logged.", _after_query_keyboard())
    return ConversationHandler.END


async def timed_out(update, context):
    context.user_data.pop('rp', None)
    chat = update.effective_chat if update else None
    if chat is not None:
        await chat.send_message("⌛ That took too long, so I cancelled it. Start again any time with /report or /events.")
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------
def _tracking(fn):
    """Remember which step the user is on, so Back knows where to go."""
    async def wrapped(update, context):
        result = await fn(update, context)
        if isinstance(result, int) and 'rp' in context.user_data:
            context.user_data['rp']['_step'] = result
        return result
    wrapped.__name__ = fn.__name__
    return wrapped


def build_report_conversation():
    text = filters.TEXT & ~filters.COMMAND
    skip = CommandHandler('skip', report_skip)
    t = _tracking
    return ConversationHandler(
        entry_points=[CommandHandler('report', t(report_entry)),
                      CallbackQueryHandler(t(report_entry), pattern=r'^menu:report$')],
        states={
            WHEN: [CallbackQueryHandler(t(report_when_button), pattern=r'^rp:when:\w+$'),
                   MessageHandler(text, t(report_when_text))],
            TYPE: [CallbackQueryHandler(t(report_type), pattern=r'^rp:type:\w+$')],
            LOCATION: [MessageHandler(text, t(report_location))],
            ISSUE: [MessageHandler(text, t(report_issue))],
            MATCH: [CallbackQueryHandler(t(report_match), pattern=r'^rp:m:\w+$')],
            SPECIFIC: [MessageHandler(text, t(report_specific_text)),
                       CallbackQueryHandler(t(report_skip), pattern=r'^rp:skip$'), skip],
            PRIORITY: [CallbackQueryHandler(t(report_priority), pattern=r'^rp:pri:\w+$')],
            PHOTO: [MessageHandler(filters.PHOTO, t(report_photo)),
                    CallbackQueryHandler(t(report_skip), pattern=r'^rp:skip$'), skip],
            CONFIRM: [CallbackQueryHandler(report_confirm, pattern=r'^rp:ok$')],
            ConversationHandler.TIMEOUT: [MessageHandler(filters.ALL, timed_out),
                                          CallbackQueryHandler(timed_out)],
        },
        fallbacks=[CommandHandler('cancel', report_cancel),
                   CallbackQueryHandler(report_cancel, pattern=r'^rp:cancel$'),
                   CallbackQueryHandler(t(report_back), pattern=r'^rp:back$')],
        conversation_timeout=CONVERSATION_TIMEOUT,
        name='report_defect',
    )


def build_events_conversation():
    return ConversationHandler(
        entry_points=[CommandHandler('events', events_entry),
                      CallbackQueryHandler(events_entry, pattern=r'^menu:events$')],
        states={
            EV_WHEN: [CallbackQueryHandler(events_quick, pattern=r'^ev:(today|tomorrow|week)$'),
                      CallbackQueryHandler(events_pick, pattern=r'^ev:pick$')],
            EV_TYPED: [MessageHandler(filters.TEXT & ~filters.COMMAND, events_typed)],
            ConversationHandler.TIMEOUT: [MessageHandler(filters.ALL, timed_out),
                                          CallbackQueryHandler(timed_out)],
        },
        fallbacks=[CommandHandler('cancel', events_cancel),
                   CallbackQueryHandler(events_cancel, pattern=r'^ev:cancel$')],
        conversation_timeout=CONVERSATION_TIMEOUT,
        name='event_query',
    )
