"""
Maintenance browsing: /service, the per-trade commands, /pending, /myjobs.

Same commands and same message shapes the FM chatbot always had -- staff read
these daily -- but every one now queries the database instead of re-reading a
spreadsheet off a OneDrive sync.

Each handler passes a query-and-render function to run_db, which
returns a finished string. Nothing that is still attached to a session ever
escapes back to the event loop; see botapp/db.py.
"""

import logging

import datetime

from botapp import config
from botapp.auth import require_member
from botapp.db import run_db
from botapp.ui import category_keyboard, reply
from botapp.fm import formatters
from botapp.services import maintenance_service

logger = logging.getLogger(__name__)


# --- render functions: these run inside an app context ---------------------
def _render_dashboard():
    return formatters.dashboard_message(maintenance_service.summary_counts())


def _render_category(key):
    return formatters.category_message(key, maintenance_service.jobs_for_category(key))


def _render_pending():
    jobs = maintenance_service.list_jobs(outstanding=True)
    return formatters.pending_message(jobs)


def _render_my_jobs(user_id):
    # list_jobs treats a falsy technician_id as "no filter", which would show a
    # member with no mapped web account EVERY job. Nothing can be assigned to
    # them, so say so instead.
    if not user_id:
        return formatters.my_jobs_message([])
    jobs = maintenance_service.list_jobs(technician_id=user_id, outstanding=True)
    return formatters.my_jobs_message(jobs)


def _count_jobs():
    return len(maintenance_service.list_jobs())


# --- handlers --------------------------------------------------------------
@require_member
async def service_command(update, context, user):
    """/service -- the routine maintenance dashboard."""
    try:
        text = await run_db(_render_dashboard)
        await reply(update, text, category_keyboard())
    except Exception as exc:
        logger.exception('/service failed')
        await reply(update, formatters.error_message(exc))


@require_member
async def category_command(update, context, user, key):
    """
    /acmv, /lift, /electrical, /fire, /plumbing.

    One function serves all of them: `key` is bound per command with
    functools.partial in main(), which is why adding a sixth trade to
    fm/catalog.py needs no new code here.
    """
    try:
        text = await run_db(_render_category, key)
        await reply(update, text, category_keyboard())
    except Exception as exc:
        logger.exception('/%s failed', key)
        await reply(update, formatters.error_message(exc))


@require_member
async def pending_command(update, context, user):
    """/pending -- every job across all trades that is not yet completed."""
    try:
        text = await run_db(_render_pending)
        await reply(update, text, category_keyboard())
    except Exception as exc:
        logger.exception('/pending failed')
        await reply(update, formatters.error_message(exc))


@require_member
async def my_jobs_command(update, context, user):
    """/myjobs -- outstanding maintenance assigned to you."""
    try:
        text = await run_db(_render_my_jobs, user.user_id)
        await reply(update, text, category_keyboard())
    except Exception as exc:
        logger.exception('/myjobs failed')
        await reply(update, formatters.error_message(exc))


@require_member
async def refresh_command(update, context, user):
    """
    /refresh -- kept from the spreadsheet era.

    There is no cache to bust any more; the database is the source of truth and
    every command already reads it live. It stays because staff have the habit,
    and answering with a live count is a useful "yes, I can see your edit".
    """
    try:
        count = await run_db(_count_jobs)
        await reply(
            update,
            f"🔄 <b>Up to date.</b>\n{count} maintenance job(s) in the system.\n\n"
            "<i>Data is read live from the database, so it is never stale.</i>",
            category_keyboard(),
        )
    except Exception as exc:
        logger.exception('/refresh failed')
        await reply(update, formatters.error_message(exc))


# --- calendar --------------------------------------------------------------
CALENDAR_WINDOWS = {'today': 0, 'week': 6, 'month': 29}
CALENDAR_TITLES = {'today': 'Today', 'week': 'Next 7 days', 'month': 'Next 30 days',
                   'overdue': 'Overdue maintenance'}


def _render_calendar(mode, today):
    if mode == 'overdue':
        entries = maintenance_service.overdue_entries(today)
        return formatters.calendar_message(
            CALENDAR_TITLES[mode], entries, today,
            empty="✅ Nothing is overdue.", show_overdue_hint=False)

    end = today + datetime.timedelta(days=CALENDAR_WINDOWS[mode])
    entries = maintenance_service.calendar_entries(today, end)
    overdue = len(maintenance_service.overdue_entries(today))
    return formatters.calendar_message(
        CALENDAR_TITLES[mode], entries, today,
        empty="Nothing scheduled in this period.", overdue_count=overdue)


@require_member
async def calendar_command(update, context, user, mode=None):
    """
    /calendar [today|week|month|overdue], plus the /today and /overdue shortcuts.

    `mode` is bound by functools.partial for the shortcuts; for /calendar it
    comes from the first argument and defaults to a week.
    """
    if mode is None:
        arg = (context.args[0].lower() if context.args else 'week')
        if arg not in CALENDAR_TITLES:
            await reply(update, "Use <code>/calendar today</code>, <code>week</code>, "
                                "<code>month</code> or <code>overdue</code>.")
            return
        mode = arg
    try:
        text = await run_db(_render_calendar, mode, config.today())
        await reply(update, text, category_keyboard())
    except Exception as exc:
        logger.exception('/calendar failed')
        await reply(update, formatters.error_message(exc))
