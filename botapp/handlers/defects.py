"""
Defect commands: /defects, /mydefects, and the /report conversation.

/report is the reason the bot exists as more than a viewer. The BMS README
listed "a simple mobile version for more seamless defect logging" as a future
update; a guided chat conversation is that, without building a mobile app.
"""

import base64
import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from botapp.auth import require_member
from botapp.db import run_db
from botapp.ui import buildings_keyboard, priority_keyboard, reply
from botapp.fm import formatters
from botapp.actor import Actor
from botapp.services import defect_service
from botapp.services.defect_service import DefectError

logger = logging.getLogger(__name__)

# Conversation states
TITLE, DESCRIPTION, BUILDING, PRIORITY, PHOTO, CONFIRM = range(6)

# Telegram offers each photo in several sizes. Picking the largest one under
# this budget keeps the stored data URI sensible without pulling in Pillow just
# to resize -- the web app stores base64 in a Text column, so a 4MB original
# would bloat every row and every /api/analytics/export.
MAX_PHOTO_BYTES = 400_000


# ---------------------------------------------------------------------------
# Read-only commands
# ---------------------------------------------------------------------------
def _render_defects(actor, assigned_only):
    defects = defect_service.list_visible_defects(actor, assigned_only=assigned_only)
    heading = 'Your Assigned Defects' if assigned_only else 'Open Defects'
    return formatters.defect_list_message(defects, heading)


@require_member
async def defects_command(update, context, user):
    """/defects -- open defects this user is allowed to see."""
    try:
        text = await run_db(_render_defects, user, False)
        await reply(update, text)
    except Exception as exc:
        logger.exception('/defects failed')
        await reply(update, formatters.error_message(exc))


@require_member
async def my_defects_command(update, context, user):
    """/mydefects -- defects assigned to the linked web account."""
    try:
        text = await run_db(_render_defects, user, True)
        await reply(update, text)
    except Exception as exc:
        logger.exception('/mydefects failed')
        await reply(update, formatters.error_message(exc))


# ---------------------------------------------------------------------------
# /report conversation
# ---------------------------------------------------------------------------
def _building_options():
    return [
        {'id': b.id, 'name': b.name}
        for b in defect_service.buildings_for_picker()
    ]


def _create(actor, data):
    defect = defect_service.create_defect(
        actor,
        title=data['title'],
        description=data['description'],
        building_id=data['building_id'],
        priority=data['priority'],
        initial_report=data.get('initial_report'),
        initial_report_image=data.get('image'),
    )
    return formatters.defect_created_message(defect)


@require_member
async def report_start(update, context, user):
    """Entry point."""
    context.user_data['report'] = {'actor': user}
    await reply(
        update,
        "📝 <b>New defect</b>  (1 of 5)\n\n"
        "What is the problem, in a few words?\n"
        "<i>e.g. \"Cracked lobby tile\"</i>\n\n"
        "Send /cancel at any point to stop.",
    )
    return TITLE


async def report_title(update, context):
    title = (update.message.text or '').strip()
    if len(title) < 3:
        await reply(update, "That is a little short. Give the defect a clear title.")
        return TITLE

    context.user_data['report']['title'] = title
    await reply(
        update,
        "📝 <b>New defect</b>  (2 of 5)\n\n"
        "Now describe it. What is wrong, and where exactly?",
    )
    return DESCRIPTION


async def report_description(update, context):
    description = (update.message.text or '').strip()
    if len(description) < 5:
        await reply(update, "Please give a bit more detail so whoever picks this up knows what to expect.")
        return DESCRIPTION

    context.user_data['report']['description'] = description

    buildings = await run_db(_building_options)
    if not buildings:
        await reply(update, "⚠️ No buildings are set up yet. Ask an admin to add one first.")
        context.user_data.pop('report', None)
        return ConversationHandler.END

    context.user_data['report']['_buildings'] = {str(b['id']): b['name'] for b in buildings}
    await reply(
        update,
        "📝 <b>New defect</b>  (3 of 5)\n\nWhich building?",
        buildings_keyboard(buildings),
    )
    return BUILDING


async def report_building(update, context):
    query = update.callback_query
    await query.answer()

    if query.data == 'report:cancel':
        return await report_cancel(update, context)

    building_id = query.data.split(':', 1)[1]
    report = context.user_data.get('report', {})
    report['building_id'] = int(building_id)
    report['building_name'] = report.get('_buildings', {}).get(building_id, '')

    await reply(
        update,
        "📝 <b>New defect</b>  (4 of 5)\n\nHow urgent is it?",
        priority_keyboard(),
    )
    return PRIORITY


async def report_priority(update, context):
    query = update.callback_query
    await query.answer()

    if query.data == 'report:cancel':
        return await report_cancel(update, context)

    context.user_data['report']['priority'] = query.data.split(':', 1)[1]

    await reply(
        update,
        "📝 <b>New defect</b>  (5 of 5)\n\n"
        "Send a photo if you have one, or /skip to finish without.",
    )
    return PHOTO


async def report_photo(update, context):
    """
    Store the photo as a base64 data URI, matching what the web app writes.

    DefectForm.jsx resizes client-side and POSTs a data URI into
    defects.initial_report_image, a Text column. We pick the largest Telegram
    size that fits the budget rather than resizing, so both front-ends produce
    the same kind of value with no image library involved.
    """
    sizes = update.message.photo or []
    if not sizes:
        await reply(update, "That did not come through as a photo. Try again, or /skip.")
        return PHOTO

    chosen = next(
        (s for s in reversed(sizes) if (s.file_size or 0) <= MAX_PHOTO_BYTES),
        sizes[0],
    )

    try:
        telegram_file = await chosen.get_file()
        raw = bytes(await telegram_file.download_as_bytearray())
    except Exception:
        logger.exception('photo download failed')
        await reply(update, "⚠️ I could not download that photo. Send another, or /skip.")
        return PHOTO

    encoded = base64.b64encode(raw).decode('ascii')
    context.user_data['report']['image'] = f'data:image/jpeg;base64,{encoded}'

    return await _show_summary(update, context)


async def report_skip_photo(update, context):
    return await _show_summary(update, context)


async def _show_summary(update, context):
    report = context.user_data.get('report', {})
    await reply(
        update,
        "\n".join([
            "🔍 <b>Ready to submit</b>",
            "",
            f"   Title: {formatters._esc(report.get('title'))}",
            f"   Building: {formatters._esc(report.get('building_name'))}",
            f"   Priority: {formatters._esc(report.get('priority'))}",
            f"   Photo: {'yes' if report.get('image') else 'no'}",
            "",
            f"<i>{formatters._esc(report.get('description'))}</i>",
            "",
            "Send /confirm to log it, or /cancel to discard.",
        ]),
    )
    return CONFIRM


async def report_confirm(update, context):
    report = context.user_data.get('report')
    if not report:
        await reply(update, "Nothing to submit. Start again with /report.")
        return ConversationHandler.END

    report['initial_report'] = f"Reported via Telegram by {report['actor'].name}"

    try:
        text = await run_db(_create, report['actor'], report)
    except DefectError as exc:
        await reply(update, f"⚠️ {formatters._esc(str(exc))}\n\nStart again with /report.")
        context.user_data.pop('report', None)
        return ConversationHandler.END
    except Exception as exc:
        logger.exception('/report submit failed')
        await reply(update, formatters.error_message(exc))
        context.user_data.pop('report', None)
        return ConversationHandler.END

    context.user_data.pop('report', None)
    await reply(update, text)
    return ConversationHandler.END


async def report_cancel(update, context):
    context.user_data.pop('report', None)
    await reply(update, "❎ Cancelled. Nothing was logged.")
    return ConversationHandler.END


def build_report_conversation():
    """
    The /report flow.

    per_message is left False on purpose: the conversation mixes text steps
    with inline-button steps, and per-message tracking only works when every
    state is a callback query.
    """
    return ConversationHandler(
        entry_points=[CommandHandler('report', report_start)],
        states={
            TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, report_title)],
            DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, report_description)],
            BUILDING: [CallbackQueryHandler(report_building, pattern=r'^(bld:\d+|report:cancel)$')],
            PRIORITY: [CallbackQueryHandler(report_priority, pattern=r'^(pri:\w+|report:cancel)$')],
            PHOTO: [
                MessageHandler(filters.PHOTO, report_photo),
                CommandHandler('skip', report_skip_photo),
            ],
            CONFIRM: [CommandHandler('confirm', report_confirm)],
        },
        fallbacks=[CommandHandler('cancel', report_cancel)],
        name='report_defect',
    )
