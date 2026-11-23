"""
Find the existing records a new report most resembles.

The guided report flow does not start by creating anything. It describes the
problem (when, which equipment type, where, what), and this module looks through
BOTH stores for the closest records:

  * the scheduled store (maintenance_jobs: scheduled work and events)
  * the unscheduled store (earlier open defect reports)

The score is deliberately plain and explainable: the user is shown WHY each
match was suggested. For candidates of the chosen equipment type:

    score = 100 * (0.25 * time + 0.35 * location + 0.40 * issue)

each part in [0, 1]. Tune MIN_SCORE / MAX_MATCHES here; nothing else changes.
"""

import datetime
import difflib
import re
from dataclasses import dataclass, field

from core.models import Defect, MaintenanceJob

MIN_SCORE = 40          # below this a record is not worth suggesting
MAX_MATCHES = 3         # per store
SCHEDULED_SLACK = datetime.timedelta(days=1)    # "during" a job includes a day either side
SCHEDULED_FADE_DAYS = 7
UNSCHEDULED_SLACK = datetime.timedelta(days=1)
UNSCHEDULED_FADE_DAYS = 14

_STOP = frozenset('a an the at in on of to and or is are was were it its for with near by from this that '
                  'there here has have had not no be been'.split())


@dataclass
class Match:
    store: str                  # 'scheduled' | 'unscheduled'
    record_id: int
    label: str                  # one line the bot can show
    score: int
    reasons: list = field(default_factory=list)


def tokens(text):
    out = set()
    for word in re.findall(r'[a-z0-9]+', (text or '').lower()):
        if word in _STOP:
            continue
        out.add(word[:-1] if len(word) > 3 and word.endswith('s') else word)
    return out


def text_similarity(a, b):
    """0..1: how much of the shorter text the longer one contains, blended with a fuzzy ratio."""
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    containment = len(ta & tb) / min(len(ta), len(tb))
    ratio = difflib.SequenceMatcher(None, ' '.join(sorted(ta)), ' '.join(sorted(tb))).ratio()
    return round(0.6 * containment + 0.4 * ratio, 4)


def _fade(delta, fade_days):
    days = delta.total_seconds() / 86400.0
    return max(0.0, 1.0 - days / fade_days)


def _job_window(job):
    """(start, end) of the scheduled item, from the timeline or, failing that, its dates."""
    if job.starts_at or job.ends_at:
        start = job.starts_at or job.ends_at
        end = job.ends_at or job.starts_at
        return start, end
    day = job.next_job_date or job.estimated_completion
    if day:
        start = datetime.datetime.combine(day, datetime.time())
        return start, start + datetime.timedelta(hours=23, minutes=59)
    return None


def scheduled_time_score(job, when):
    window = _job_window(job)
    if window is None:
        return 0.0, None
    start, end = window
    if start - SCHEDULED_SLACK <= when <= end + SCHEDULED_SLACK:
        return 1.0, 'falls within its scheduled time'
    off = (start - when) if when < start else (when - end)
    score = _fade(off, SCHEDULED_FADE_DAYS)
    return score, (f'{int(off.total_seconds() // 86400)} day(s) from its scheduled time' if score else None)


def unscheduled_time_score(defect, when):
    at = defect.occurred_at or defect.created_at
    if at is None:
        return 0.0, None
    off = abs(when - at)
    if off <= UNSCHEDULED_SLACK:
        return 1.0, 'reported around the same time'
    score = _fade(off - UNSCHEDULED_SLACK, UNSCHEDULED_FADE_DAYS)
    return score, (f'reported {int(off.total_seconds() // 86400)} day(s) apart' if score else None)


def _score(time_part, loc_part, issue_part):
    return int(round(100 * (0.25 * time_part + 0.35 * loc_part + 0.40 * issue_part)))


def _reasons(time_reason, loc_part, issue_part):
    out = ['same equipment type']
    if time_reason:
        out.append(time_reason)
    if loc_part >= 0.5:
        out.append('similar location')
    if issue_part >= 0.4:
        out.append('similar description')
    return out


def find_matches(equipment_type_id, when, location, issue):
    """
    Returns {'scheduled': [Match...], 'unscheduled': [Match...]}, best first,
    each list capped at MAX_MATCHES and cut at MIN_SCORE. Both empty means
    nothing similar exists: the flow then offers to create a fresh report.
    """
    scheduled, unscheduled = [], []

    jobs = MaintenanceJob.query.filter(MaintenanceJob.equipment_type_id == equipment_type_id).all()
    for job in jobs:
        t, why = scheduled_time_score(job, when)
        loc = text_similarity(location, f'{job.location} {job.building.name if job.building else ""}')
        iss = text_similarity(issue, f'{job.description} {job.schedule_note or ""}')
        score = _score(t, loc, iss)
        if score >= MIN_SCORE:
            scheduled.append(Match('scheduled', job.id,
                                   f'{job.job_ref}: {job.description} ({job.location})', score,
                                   _reasons(why, loc, iss)))

    defects = (Defect.query
               .filter(Defect.equipment_type_id == equipment_type_id,
                       Defect.kind == 'unscheduled',
                       Defect.deleted_at.is_(None),
                       Defect.merged_into_id.is_(None),
                       Defect.status != 'Completed')
               .all())
    for d in defects:
        t, why = unscheduled_time_score(d, when)
        loc = text_similarity(location, f'{d.location or ""} {d.building.name if d.building else ""}')
        iss = text_similarity(issue, f'{d.title} {d.description} {d.specific_equipment or ""}')
        score = _score(t, loc, iss)
        if score >= MIN_SCORE:
            unscheduled.append(Match('unscheduled', d.id,
                                     f'#{d.id}: {d.title} ({d.location or "no location"})', score,
                                     _reasons(why, loc, iss)))

    key = lambda m: (-m.score, m.record_id)
    return {'scheduled': sorted(scheduled, key=key)[:MAX_MATCHES],
            'unscheduled': sorted(unscheduled, key=key)[:MAX_MATCHES]}


SCHEDULED_TIE_BONUS = 5     # a scheduled item wins a near tie: "if it is scheduled, it is scheduled"
MAX_SUGGESTIONS = 5


def rank(found, limit=MAX_SUGGESTIONS):
    """
    One list, most similar first, across both stores. A scheduled item is
    preferred only when it is about as similar as an unscheduled one (within
    SCHEDULED_TIE_BONUS points); a clearly better unscheduled match comes first.
    """
    merged = found['scheduled'] + found['unscheduled']
    key = lambda m: (-(m.score + (SCHEDULED_TIE_BONUS if m.store == 'scheduled' else 0)), m.record_id)
    return sorted(merged, key=key)[:limit]
