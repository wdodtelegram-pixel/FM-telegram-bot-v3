"""
Telegram HTML message builders.

Ported from the FM chatbot's formatters.py. The message shapes are unchanged --
staff already read these every day -- but the inputs are now MaintenanceJob and
Defect model instances instead of pandas rows, and there are new builders for
the defect side of the platform.

Deliberately free of Telegram imports so it stays testable on its own.
"""

from __future__ import annotations

import html
import math
from typing import Any

from botapp.fm import catalog
from botapp.fm.date_utils import to_week_format


def _is_missing(value: Any) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))


def _esc(value: Any) -> str:
    """
    Escape text before it goes into an HTML message.

    "AHU <3" or "Level 5 & 6" typed into a description would otherwise make
    Telegram reject the whole message with a parse error.
    """
    if _is_missing(value):
        return "-"
    text = str(value).strip()
    return html.escape(text) if text else "-"


def _schedule(job_date, note=None) -> str:
    """Render a schedule column: the real date, else the note staff typed, else '-'."""
    if job_date is not None:
        return to_week_format(job_date)
    return _esc(note) if note else "-"


# ---------------------------------------------------------------------------
# Maintenance
# ---------------------------------------------------------------------------
def welcome_message(user=None) -> str:
    """
    The reply to /start and /help.

    The category list is generated from the catalog rather than typed out, so
    adding a sixth trade adds a sixth line here with no edit.
    """
    lines = [
        "👷 <b>Building &amp; Facilities Management</b>",
        "",
        "Maintenance schedules and building defects, in one place.",
    ]

    if user is None:
        lines += [
            "",
            "🔒 <b>You are not authorised to use this bot.</b>",
            "",
            "Ask an administrator to add you, and give them the ID shown by /start.",
        ]
        return "\n".join(lines)

    lines += [
        f"Signed in as <b>{_esc(user.name)}</b>.",
        "",
        "<b>Maintenance</b>",
        "/service — routine maintenance dashboard",
        "",
        "Drill into a trade, e.g. /acmv for ACMV jobs:",
    ]

    for key, meta in catalog.CATEGORIES.items():
        lines.append(f"/{key} — {meta['emoji']} {meta['blurb']}")

    lines += [
        "",
        "<b>Defects</b>",
        "/defects — open defects you can see",
        "/report — report a new defect",
        "",
        "<b>Yours</b>",
        "/myjobs — maintenance jobs assigned to you",
        "/mydefects — defects assigned to you",
        "",
        "<b>Schedule</b>",
        "/calendar — agenda: week (default), today, month, overdue",
        "/today — what is scheduled today",
        "/overdue — maintenance past its due date",
        "",
        "<b>Other</b>",
        "/pending — all maintenance jobs not yet completed",
        "/refresh — reload the latest data",
        "/whoami — show who you are signed in as",
        "/help — show this menu again",
    ]

    return "\n".join(lines)


def dashboard_message(summary: dict) -> str:
    """
    The reply to /service -- a one-screen overview of every trade, so a duty
    manager can see the whole position at a glance then drill in.
    """
    lines = [
        "📋 <b>Routine Maintenance Dashboard</b>",
        "",
    ]

    grand_total = 0
    grand_done = 0

    for key, meta in catalog.CATEGORIES.items():
        stats = summary.get(key, {})
        total = stats.get("total", 0)
        done = stats.get(catalog.STATUS_COMPLETED, 0)
        grand_total += total
        grand_done += done

        lines.append(f"{meta['emoji']} <b>{meta['name']}</b>  (/{key})")

        if total == 0:
            lines.append("   No jobs recorded")
        else:
            lines.append(
                f"   ⚪ {stats.get(catalog.STATUS_YET_TO_START, 0)}   "
                f"🟡 {stats.get(catalog.STATUS_IN_PROGRESS, 0)}   "
                f"🟢 {done}   "
                f"— {total} job(s)"
            )
        lines.append("")

    lines.append("──────────────")
    lines.append(f"<b>Total:</b> {grand_total} job(s) · {grand_done} completed")
    lines.append("")
    lines.append("<i>⚪ Yet to start  🟡 In progress  🟢 Completed</i>")
    lines.append("Tap a category command above for full details.")

    return "\n".join(lines)


def _job_block(job) -> str:
    """
    Render one maintenance job as a compact block.

    Shared by the category view and /myjobs so a job always looks the same.
    """
    icon = catalog.status_icon(job.status)
    lines = [
        f"{icon} <b>{_esc(job.description)}</b>  <code>{_esc(job.job_ref)}</code>",
        f"   📍 Location: {_esc(job.location)}",
        f"   🔧 Type: {_esc(job.maintenance_type)} maintenance",
        f"   📊 Status: {_esc(job.status)}",
        f"   🗓 Est. completion: {_schedule(job.estimated_completion, job.schedule_note)}",
        f"   🔁 Next job: {_schedule(job.next_job_date)}",
    ]
    if job.building is not None:
        lines.insert(2, f"   🏢 Building: {_esc(job.building.name)}")
    return "\n".join(lines)


def category_message(category_key: str, jobs) -> str:
    """The reply to /acmv, /lift, /electrical, /fire and /plumbing."""
    meta = catalog.CATEGORIES[category_key]
    header = f"{meta['emoji']} <b>{meta['name'].upper()} — Routine Maintenance</b>"

    if not jobs:
        return (
            f"{header}\n\n"
            "No jobs are currently recorded for this category.\n"
            "Use /service to see all categories."
        )

    blocks = [_job_block(job) for job in jobs]
    footer = (
        "──────────────\n"
        f"<i>{len(jobs)} job(s) in this category · /service for the full dashboard</i>"
    )
    return f"{header}\n\n" + "\n\n".join(blocks) + f"\n\n{footer}"


def pending_message(jobs) -> str:
    """
    The reply to /pending -- every job not yet completed, grouped by trade.
    The view a duty officer wants at the start of a shift.
    """
    if not jobs:
        return (
            "✅ <b>No outstanding jobs.</b>\n"
            "Every maintenance job is marked completed."
        )

    lines = ["⏳ <b>Outstanding Jobs (all trades)</b>", ""]

    for key, meta in catalog.CATEGORIES.items():
        rows = [job for job in jobs if job.category == meta["name"]]
        if not rows:
            continue

        lines.append(f"{meta['emoji']} <b>{meta['name']}</b>")
        for job in rows:
            lines.append(
                f"   {catalog.status_icon(job.status)} "
                f"{_esc(job.description)} — "
                f"{_esc(job.location)} — "
                f"due {_schedule(job.estimated_completion, job.schedule_note)}"
            )
        lines.append("")

    lines.append(f"<i>{len(jobs)} outstanding job(s) in total.</i>")
    return "\n".join(lines)


def my_jobs_message(jobs) -> str:
    """The reply to /myjobs -- maintenance assigned to the linked user."""
    if not jobs:
        return "✅ <b>No maintenance jobs are assigned to you.</b>"

    blocks = [_job_block(job) for job in jobs]
    return (
        "🔧 <b>Your Maintenance Jobs</b>\n\n"
        + "\n\n".join(blocks)
        + f"\n\n<i>{len(jobs)} job(s) assigned to you.</i>"
    )


# ---------------------------------------------------------------------------
# Defects
# ---------------------------------------------------------------------------
DEFECT_STATUS_ICONS = {
    "open": "🔴",
    "reviewed": "🟣",
    "ongoing": "🟡",
    "done": "🟢",
    "completed": "⚫",
}

PRIORITY_ICONS = {"high": "🔺", "medium": "🔸", "low": "🔹"}


def defect_status_icon(status) -> str:
    return DEFECT_STATUS_ICONS.get((status or "").strip().lower(), "⚪")


def _defect_block(defect) -> str:
    """Render one defect as a compact block, shared by /defects and /mydefects."""
    icon = defect_status_icon(defect.status)
    priority = PRIORITY_ICONS.get((defect.priority or "").lower(), "")

    lines = [
        f"{icon} <b>{_esc(defect.title)}</b>  <code>#{defect.id}</code>",
        f"   📊 Status: {_esc(defect.status)}",
        f"   {priority} Priority: {_esc(defect.priority)}",
    ]
    if defect.building is not None:
        lines.append(f"   🏢 Building: {_esc(defect.building.name)}")
    if defect.technician is not None:
        lines.append(f"   👷 Technician: {_esc(defect.technician.name)}")
    if defect.created_at is not None:
        lines.append(f"   🗓 Reported: {defect.created_at.strftime('%d %b %Y')}")
    return "\n".join(lines)


def defect_list_message(defects, heading="Open Defects") -> str:
    """The reply to /defects and /mydefects."""
    if not defects:
        return f"✅ <b>No defects to show.</b>\nNothing matches <i>{_esc(heading)}</i>."

    blocks = [_defect_block(defect) for defect in defects]
    return (
        f"🛠 <b>{_esc(heading)}</b>\n\n"
        + "\n\n".join(blocks)
        + f"\n\n<i>{len(defects)} defect(s).</i>"
    )


def defect_created_message(defect) -> str:
    """Confirmation shown at the end of the /report conversation."""
    return "\n".join([
        "✅ <b>Defect reported.</b>",
        "",
        _defect_block(defect),
        "",
        "<i>It will be reviewed shortly.</i>",
    ])


def defect_assigned_message(defect) -> str:
    """
    Pushed to the assigned person when a defect is assigned to their web account.
    Sent by services/notifications.py, not by the bot process.
    """
    return "\n".join([
        "🔔 <b>A defect has been assigned to you.</b>",
        "",
        _defect_block(defect),
        "",
        f"<i>{_esc(defect.description)}</i>",
        "",
        "Use /mydefects to see everything assigned to you.",
    ])


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------
CALENDAR_MAX_ENTRIES = 60

_KIND_LABEL = {'due': 'due', 'next': 'next service', 'overdue': 'overdue'}


def calendar_message(title, entries, today, empty, overdue_count=0, show_overdue_hint=True) -> str:
    """
    A day-by-day agenda of maintenance jobs.

    `entries` are (date, kind, job) tuples, already sorted. Capped so a busy
    month cannot produce an unreadable wall of text.
    """
    lines = [f"📅 <b>{_esc(title)}</b>", ""]

    if not entries:
        lines.append(empty)
    else:
        shown, hidden = entries[:CALENDAR_MAX_ENTRIES], max(0, len(entries) - CALENDAR_MAX_ENTRIES)
        current = None
        for day, kind, job in shown:
            if day != current:
                if current is not None:
                    lines.append("")
                current = day
                lines.append(f"<b>{_day_heading(day, today)}</b>")
            icon = catalog.status_icon(job.status)
            lines.append(
                f"   {icon} {_esc(job.description)} — {_esc(job.location)} "
                f"<code>{_esc(job.job_ref)}</code> · <i>{_KIND_LABEL[kind]}</i>"
            )
        if hidden:
            lines += ["", f"<i>…and {hidden} more. Narrow it with /today or /calendar week.</i>"]

    if show_overdue_hint and overdue_count:
        lines += ["", f"⚠️ <b>{overdue_count} overdue</b> — see /overdue"]

    return "\n".join(lines)


def _day_heading(day, today) -> str:
    text = day.strftime("%a %d %b %Y")
    delta = (day - today).days
    if delta == 0:
        return f"{text} (today)"
    if delta == 1:
        return f"{text} (tomorrow)"
    if delta < 0:
        n = -delta
        return f"{text} ({n} day{'s' if n != 1 else ''} overdue)"
    return text


# ---------------------------------------------------------------------------
# Account + errors
# ---------------------------------------------------------------------------
def whoami_message(user) -> str:
    return "\n".join([
        "👤 <b>Your membership</b>",
        "",
        f"   Name: {_esc(user.name)}",
        "   Access: full",
        "   Web account: " + (
            f"linked (#{user.user_id}) — /myjobs, /mydefects and assignment alerts work"
            if user.user_id else "not linked — /myjobs and /mydefects will be empty"),
        "",
        "Access is managed by your administrator.",
    ])


def not_authorised_message(chat_id) -> str:
    return (
        "🔒 <b>You are not authorised to use this bot.</b>\n\n"
        "Send this ID to an administrator and ask to be added:\n"
        f"<code>{chat_id}</code>"
    )


def error_message(exc: Exception) -> str:
    """
    Turn an internal exception into something a facilities officer can act on,
    rather than showing a Python traceback in a chat window.
    """
    return (
        "⚠️ <b>Something went wrong.</b>\n\n"
        f"<code>{html.escape(str(exc))[:300]}</code>\n\n"
        "Please try again in a moment."
    )
