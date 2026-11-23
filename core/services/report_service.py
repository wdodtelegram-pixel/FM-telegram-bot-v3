"""
Recording a report: match first, create last.

The guided flow calls suggest() with what the user described, shows the closest
records, and then calls record_report() with the user's choice:

  ('scheduled', job_id)     it is that scheduled item -> a defect linked to it
  ('unscheduled', defect_id) it is that earlier report -> added to it, not duplicated
  ('new', None)             nothing similar -> a fresh unscheduled report

Reporter attribution, priority and the initial-report comment follow the
original /report rules.
"""

import datetime

from sqlalchemy import func

from core import similarity
from core.db import db
from core.models import Building, Defect, DefectComment, EquipmentType, MaintenanceJob

PRIORITIES = ('low', 'medium', 'high')
MIN_ISSUE_CHARS = 5
MIN_LOCATION_CHARS = 2
MAX_FUTURE = datetime.timedelta(days=1)


class ReportError(Exception):
    """A report that is well-formed but cannot be recorded."""


def _clean(equipment_type_id, when, location, issue):
    etype = EquipmentType.query.get(equipment_type_id)
    if etype is None or not etype.active:
        raise ReportError('Unknown equipment type')
    location = (location or '').strip()
    issue = (issue or '').strip()
    if len(location) < MIN_LOCATION_CHARS:
        raise ReportError('Please say where it is')
    if len(issue) < MIN_ISSUE_CHARS:
        raise ReportError('Please describe the issue in a few words')
    if when is None:
        raise ReportError('A date and time is needed')
    if when > datetime.datetime.utcnow() + MAX_FUTURE:
        raise ReportError('That date is in the future')
    return etype, location, issue


def suggest(equipment_type_id, when, location, issue):
    """The closest scheduled and unscheduled records. Validates like record_report."""
    _clean(equipment_type_id, when, location, issue)
    return similarity.find_matches(equipment_type_id, when, location, issue)


def _building_for(location):
    """A known building named in the location text, if any."""
    low = (location or '').lower()
    for b in Building.query.order_by(func.length(Building.name).desc()).all():
        if b.name and b.name.lower() in low:
            return b
    return None


def _title(issue):
    first = issue.strip().splitlines()[0]
    return first if len(first) <= 70 else first[:67].rstrip() + '...'


def record_report(actor, equipment_type_id, when, location, issue, choice=('new', None),
                  specific_equipment=None, priority='medium', image=None):
    """
    Save the report according to `choice`. Returns a plain dict describing what
    happened: {'outcome', 'defect_id', 'parent_id', 'job_id', 'job_ref', 'title'}.
    """
    etype, location, issue = _clean(equipment_type_id, when, location, issue)
    priority = (priority or 'medium').lower()
    if priority not in PRIORITIES:
        raise ReportError(f"Priority must be one of: {', '.join(PRIORITIES)}")

    kind, target_id = choice
    job = parent = None
    if kind == 'scheduled':
        job = MaintenanceJob.query.get(target_id)
        if job is None or job.equipment_type_id != etype.id:
            raise ReportError('That scheduled item is not available')
    elif kind == 'unscheduled':
        parent = Defect.query.get(target_id)
        if (parent is None or parent.kind != 'unscheduled' or parent.deleted_at is not None
                or parent.merged_into_id is not None):
            raise ReportError('That earlier report is not available')
    elif kind != 'new':
        raise ReportError('Unknown choice')

    building = (job.building if job is not None and job.building_id else None) or _building_for(location)

    defect = Defect(
        title=_title(issue),
        description=issue,
        priority=priority,
        kind='scheduled' if job is not None else 'unscheduled',
        occurred_at=when,
        equipment_type_id=etype.id,
        location=location if (location or not job) else job.location,
        specific_equipment=(specific_equipment or '').strip() or None,
        maintenance_job_id=job.id if job is not None else None,
        merged_into_id=parent.id if parent is not None else None,
        building_id=building.id if building is not None else None,
        initial_report_image=image,
        # A mapped member is attributed to their web account so the website's
        # per-user views keep working; everyone else is a bot reporter.
        reporter_id=actor.user_id,
        bot_reporter_id=None if actor.user_id else actor.member_id,
        reporter_label=actor.name,
    )
    db.session.add(defect)
    db.session.flush()

    note = f'Reported via Telegram by {actor.name}'
    db.session.add(DefectComment(defect_id=defect.id, initial_report=note))

    if parent is not None:
        # Add the sighting to the existing report and surface it as recently updated.
        db.session.add(DefectComment(
            defect_id=parent.id,
            initial_report=f'Additional report by {actor.name} ({when:%d %b %Y %H:%M}): {issue}'))
        parent.updated_at = datetime.datetime.utcnow()

    db.session.commit()
    return {
        'outcome': {'scheduled': 'linked_scheduled', 'unscheduled': 'merged', 'new': 'created'}[kind],
        'defect_id': defect.id,
        'parent_id': parent.id if parent is not None else None,
        'job_id': job.id if job is not None else None,
        'job_ref': job.job_ref if job is not None else None,
        'title': defect.title,
    }
