"""
Week-of-month date handling for maintenance schedules.

Facilities teams schedule servicing by calendar block -- "Week 1 January 2026"
-- rather than by exact day, and that is how the source workbooks are written.

The FM chatbot stored those strings verbatim, which meant no job could ever be
sorted, range-queried, or compared against today. Here they become real dates:

    week_string_to_date("Week 1 January 2026")  ->  date(2026, 1, 1)
    to_week_format(date(2026, 1, 1))            ->  "Week 1 January 2026"

The round-trip is exact, because to_week_format buckets on (day - 1) // 7 and
week_string_to_date lands on day (n - 1) * 7 + 1 -- the first day of the block.

`to_week_format` is carried over unchanged from the chatbot's date_utils.py.
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime

# Recognises text already written in the target format. If a cell says
# "Week 2 March 2026" we trust it and just tidy the capitalisation rather than
# trying to re-parse it as a date.
_ALREADY_FORMATTED = re.compile(
    r"^\s*week\s*([1-5])\s+([a-z]+)\s+(\d{4})\s*$", re.IGNORECASE
)

_MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

_MONTH_NUMBERS = {name.lower(): index + 1 for index, name in enumerate(_MONTH_NAMES)}
_MONTH_NUMBERS.update({name[:3].lower(): index + 1 for index, name in enumerate(_MONTH_NAMES)})


def _week_of_month(day: int) -> int:
    """
    Convert a day-of-month into a week number 1-5.

    Days 1-7 are week 1, 8-14 week 2, and so on -- the "calendar block"
    definition facilities teams mean by 'week 1', not the ISO week number.
    """
    return min(5, (day - 1) // 7 + 1)


def _is_missing(value) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))


def _parse_date(text: str) -> datetime | None:
    normalized = text.strip()
    if not normalized:
        return None

    # Try ISO-like and common numeric formats first.
    iso_like = normalized.replace("/", "-").replace(".", "-")
    for fmt in (
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S",
        "%d-%m-%Y",
        "%d-%m-%y",
        "%d-%m",
    ):
        try:
            parsed = datetime.strptime(iso_like, fmt)
            if fmt == "%d-%m":
                return parsed.replace(year=datetime.now().year)
            if parsed.year < 100:
                parsed = parsed.replace(year=parsed.year + 2000)
            return parsed
        except ValueError:
            continue

    # Try written month names.
    for fmt in (
        "%d %B %Y",
        "%d %b %Y",
        "%B %d %Y",
        "%b %d %Y",
        "%d %B %y",
        "%d %b %y",
    ):
        try:
            parsed = datetime.strptime(normalized, fmt)
            if parsed.year < 100:
                parsed = parsed.replace(year=parsed.year + 2000)
            return parsed
        except ValueError:
            continue

    # Fallback parse for common day-first numeric dates.
    match = re.match(r"^(\d{1,2})[\-/](\d{1,2})[\-/](\d{2,4})$", normalized)
    if match:
        day, month, year = match.groups()
        year = int(year)
        if year < 100:
            year += 2000
        try:
            return datetime(year, int(month), int(day))
        except ValueError:
            return None

    return None


def to_week_format(value) -> str:
    """
    Turn anything -- a date, a datetime, or a spreadsheet cell -- into a
    display string.

    Returns "-" for blanks so a message never shows "NaT" or "nan" to a user,
    and returns unrecognised text unchanged, so a deliberate "TBC" or
    "On hold" written by staff still shows through.
    """
    if _is_missing(value):
        return "-"

    if isinstance(value, (datetime, date)):
        return f"Week {_week_of_month(value.day)} {_MONTH_NAMES[value.month - 1]} {value.year}"

    text = str(value).strip()
    if not text:
        return "-"

    match = _ALREADY_FORMATTED.match(text)
    if match:
        week, month, year = match.groups()
        return f"Week {week} {month.capitalize()} {year}"

    parsed = _parse_date(text)
    if parsed:
        return f"Week {_week_of_month(parsed.day)} {_MONTH_NAMES[parsed.month - 1]} {parsed.year}"

    return text


def week_string_to_date(value) -> date | None:
    """
    The inverse of to_week_format: turn a schedule cell into a real date, so
    it can be stored in a DATE column and compared against today.

    Handles the three things that actually appear in these workbooks:
      * "Week 3 January 2026"  -> date(2026, 1, 15), the first day of block 3
      * a real date or datetime -> itself
      * "-", blanks, and free text like "TBC" -> None

    Returning None for unparseable text is deliberate: the caller stores that
    text in MaintenanceJob.schedule_note so nothing a human wrote is lost.
    """
    if _is_missing(value):
        return None

    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    text = str(value).strip()
    if not text or text == "-":
        return None

    match = _ALREADY_FORMATTED.match(text)
    if match:
        week, month_name, year = match.groups()
        month = _MONTH_NUMBERS.get(month_name.lower())
        if not month:
            return None
        day = (int(week) - 1) * 7 + 1
        try:
            return date(int(year), month, day)
        except ValueError:
            return None

    parsed = _parse_date(text)
    return parsed.date() if parsed else None
