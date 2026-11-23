"""
Understanding a date/time a person typed in chat, and the quick-pick ranges.

Forgiving on purpose: "25 Nov 14:30", "25/11", "2026-11-25 09:00", "14:30",
"yesterday 14:30", "now". Anything it cannot read returns None and the bot
asks again with an example.
"""

import datetime
import re

_TIME = re.compile(r'\b(\d{1,2})[:.](\d{2})\b')
_MONTHS = {m: i for i, m in enumerate(
    ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'], start=1)}


def _date_part(text, today):
    """A date from text with the time already removed, or None. Empty text means today."""
    t = text.strip().lower().strip(',')
    if t in ('', 'today', 'now'):
        return today
    if t == 'yesterday':
        return today - datetime.timedelta(days=1)
    if t == 'tomorrow':
        return today + datetime.timedelta(days=1)

    m = re.match(r'^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$', t)
    if m:
        return _safe(int(m[1]), int(m[2]), int(m[3]))
    m = re.match(r'^(\d{1,2})[-/.](\d{1,2})(?:[-/.](\d{2,4}))?$', t)          # day first
    if m:
        year = int(m[3]) if m[3] else today.year
        return _safe(year + 2000 if year < 100 else year, int(m[2]), int(m[1]))
    m = re.match(r'^(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]{3})[a-z]*\.?(?:\s+(\d{2,4}))?$', t)   # 25 Nov [2026]
    if m and m[2] in _MONTHS:
        year = int(m[3]) if m[3] else today.year
        return _safe(year + 2000 if year < 100 else year, _MONTHS[m[2]], int(m[1]))
    m = re.match(r'^([a-z]{3})[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{2,4}))?$', t)  # Nov 25 [2026]
    if m and m[1] in _MONTHS:
        year = int(m[3]) if m[3] else today.year
        return _safe(year + 2000 if year < 100 else year, _MONTHS[m[1]], int(m[2]))
    return None


def _safe(y, m, d):
    try:
        return datetime.date(y, m, d)
    except ValueError:
        return None


def parse_when(text, now):
    """A datetime from chat text, or None. A date with no time is midday-neutral: 00:00."""
    raw = (text or '').strip()
    if not raw:
        return None
    if raw.lower() == 'now':
        return now
    hour = minute = None
    m = _TIME.search(raw)
    rest = raw
    if m:
        hour, minute = int(m[1]), int(m[2])
        if hour > 23 or minute > 59:
            return None
        rest = (raw[:m.start()] + raw[m.end():]).strip()
    day = _date_part(rest, now.date())
    if day is None:
        return None
    if hour is None:
        # "today"/"yesterday" alone mean that day at the current time; a bare date means the day.
        if rest.strip().lower() in ('today', 'yesterday', 'tomorrow'):
            return datetime.datetime.combine(day, now.time().replace(second=0, microsecond=0))
        return datetime.datetime.combine(day, datetime.time())
    return datetime.datetime.combine(day, datetime.time(hour, minute))


def parse_range(text, today):
    """
    (start, end) datetimes covering a typed day or range, or None.
    "25 Nov" -> that whole day; "25 Nov - 30 Nov" / "25/11 to 30/11" -> through the end of the last day.
    """
    raw = (text or '').strip()
    if not raw:
        return None
    parts = re.split(r'\s+(?:-|to|until|till)\s+|\s*–\s*', raw, maxsplit=1, flags=re.I)
    now = datetime.datetime.combine(today, datetime.time())
    first = parse_when(parts[0], now)
    if first is None:
        return None
    second = parse_when(parts[1], now) if len(parts) == 2 else first
    if second is None or second < first:
        return None
    return (datetime.datetime.combine(first.date(), datetime.time()),
            datetime.datetime.combine(second.date(), datetime.time(23, 59, 59)))


def quick_range(choice, today):
    """The preset ranges the event query offers: today, tomorrow, week (next 7 days)."""
    start = datetime.datetime.combine(today, datetime.time())
    if choice == 'today':
        return start, start + datetime.timedelta(hours=23, minutes=59, seconds=59)
    if choice == 'tomorrow':
        s = start + datetime.timedelta(days=1)
        return s, s + datetime.timedelta(hours=23, minutes=59, seconds=59)
    if choice == 'week':
        return start, start + datetime.timedelta(days=6, hours=23, minutes=59, seconds=59)
    raise ValueError(choice)
