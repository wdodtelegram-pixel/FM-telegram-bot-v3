"""
Load the scheduled store (scheduled maintenance + events) from a CSV.

Plain and forgiving on purpose: required columns are checked, dates are parsed,
the equipment type must be a known one, and any row that fails is skipped and
reported with its line number and reason rather than aborting the whole file.
There is deliberately no JSON-schema layer yet; `_clean_row` is the one place
to add it later.

Columns (case-insensitive; the aliases in COLUMN_ALIASES are accepted):
  job_ref, category (equipment type name or key), description, location,
  maintenance_type, status, starts_at, ends_at, estimated_completion,
  next_job_date, schedule_note
Rows with an existing job_ref update that job; the rest are created.
"""

import csv
import datetime
import io
import os
import re
from dataclasses import dataclass, field

from core.db import db
from core.equipment import get_by_key_or_name
from core.fm import catalog
from core.fm.date_utils import week_string_to_date
from core.models import MaintenanceJob

COLUMN_ALIASES = {
    'job_ref': ('job_ref', 'ref', 'job ref', 'job id', 'id', 'reference'),
    'category': ('category', 'equipment type', 'equipment_type', 'type of equipment', 'equipment', 'trade'),
    'description': ('description', 'job', 'task', 'details', 'job description'),
    'location': ('location', 'area', 'place'),
    'maintenance_type': ('maintenance_type', 'maintenance type', 'pm/cm', 'type'),
    'status': ('status',),
    'starts_at': ('starts_at', 'start', 'start date', 'start date/time', 'from', 'date/time', 'date'),
    'ends_at': ('ends_at', 'end', 'end date', 'end date/time', 'to'),
    'estimated_completion': ('estimated_completion', 'estimated completion', 'due', 'due date'),
    'next_job_date': ('next_job_date', 'next job date', 'next job', 'next service', 'next date'),
    'schedule_note': ('schedule_note', 'note', 'notes', 'remarks'),
}
REQUIRED = ('category', 'description', 'location')

_DATETIME_FORMATS = (
    '%Y-%m-%d %H:%M', '%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M', '%Y-%m-%dT%H:%M:%S',
    '%d/%m/%Y %H:%M', '%d-%m-%Y %H:%M', '%d/%m/%y %H:%M',
)


@dataclass
class ImportResult:
    created: int = 0
    updated: int = 0
    skipped: list = field(default_factory=list)      # [(line_number, reason)]
    dry_run: bool = False

    @property
    def ok(self):
        return not self.skipped

    def summary(self):
        verb = 'would be' if self.dry_run else 'were'
        return (f'{self.created} created, {self.updated} updated, {len(self.skipped)} skipped '
                f'({"nothing" if self.dry_run else "changes"} {verb} saved)')


def parse_datetime(text):
    """A datetime from a CSV cell, or None. Date-only cells become midnight."""
    text = (text or '').strip()
    if not text or text == '-':
        return None
    for fmt in _DATETIME_FORMATS:
        try:
            return datetime.datetime.strptime(text, fmt)
        except ValueError:
            continue
    day = week_string_to_date(text)        # real dates, "5 Jan 2026", "Week 3 January 2026"
    return datetime.datetime.combine(day, datetime.time()) if day else None


def _map_headers(fieldnames):
    lookup = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            lookup.setdefault(alias.lower(), canonical)
    mapping = {}
    for name in fieldnames or []:
        canonical = lookup.get((name or '').strip().lower())
        if canonical and canonical not in mapping.values():
            mapping[name] = canonical
    return mapping


def _clean_row(raw, mapping):
    """The single hook for stricter validation (e.g. a JSON schema) later."""
    row = {canonical: (raw.get(name) or '').strip() for name, canonical in mapping.items()}
    return row


def _next_ref(type_key):
    prefix = re.sub(r'[^A-Z0-9]', '', type_key.upper())[:8] or 'JOB'
    existing = [r[0] for r in db.session.query(MaintenanceJob.job_ref)
                .filter(MaintenanceJob.job_ref.like(f'{prefix}-%')).all()]
    nums = [int(m.group(1)) for ref in existing if (m := re.match(rf'^{prefix}-(\d+)$', ref))]
    return f'{prefix}-{(max(nums) + 1 if nums else 1):03d}'


def import_csv(source, dry_run=False):
    """
    Import from a path, an open text file, or CSV text. Returns an ImportResult.
    Nothing is saved when dry_run is true.
    """
    if isinstance(source, str):
        if os.path.exists(source):
            with open(source, newline='', encoding='utf-8-sig') as fh:
                text = fh.read()
        else:
            text = source
    else:
        text = source.read()

    result = ImportResult(dry_run=dry_run)
    reader = csv.DictReader(io.StringIO(text))
    mapping = _map_headers(reader.fieldnames)
    missing = [c for c in REQUIRED if c not in mapping.values()]
    if missing:
        result.skipped.append((1, f'missing required column(s): {", ".join(missing)}'))
        return result

    for line_no, raw in enumerate(reader, start=2):
        if not any((v or '').strip() for v in raw.values()):
            continue
        row = _clean_row(raw, mapping)
        try:
            with db.session.begin_nested():
                created = _apply_row(row)
            if created:
                result.created += 1
            else:
                result.updated += 1
        except ValueError as exc:
            result.skipped.append((line_no, str(exc)))

    if dry_run:
        db.session.rollback()
    else:
        db.session.commit()
    return result


def _apply_row(row):
    """Create or update one job. Raises ValueError with a human reason on a bad row."""
    etype = get_by_key_or_name(row['category'])
    if etype is None or not etype.active:
        raise ValueError(f'unknown equipment type "{row["category"]}"')
    if not row['description']:
        raise ValueError('description is empty')
    if not row['location']:
        raise ValueError('location is empty')

    starts = parse_datetime(row.get('starts_at'))
    ends = parse_datetime(row.get('ends_at'))
    if row.get('starts_at') and starts is None:
        raise ValueError(f'cannot read start "{row["starts_at"]}"')
    if row.get('ends_at') and ends is None:
        raise ValueError(f'cannot read end "{row["ends_at"]}"')
    if starts and ends and ends < starts:
        raise ValueError('end is before start')

    due = week_string_to_date(row.get('estimated_completion')) if row.get('estimated_completion') else None
    nxt = week_string_to_date(row.get('next_job_date')) if row.get('next_job_date') else None
    note = row.get('schedule_note') or None
    # Free text where a date was expected ("TBC") is kept, never discarded.
    for label in ('estimated_completion', 'next_job_date'):
        if row.get(label) and (due if label == 'estimated_completion' else nxt) is None and not note:
            note = row[label]

    mtype = catalog.canonical_type(row.get('maintenance_type'))
    status = catalog.canonical_status(row.get('status'))

    ref = row.get('job_ref') or _next_ref(etype.key)
    job = MaintenanceJob.query.filter_by(job_ref=ref).first()
    created = job is None
    if created:
        job = MaintenanceJob(job_ref=ref)
        db.session.add(job)

    job.category = etype.name
    job.equipment_type_id = etype.id
    job.description = row['description']
    job.location = row['location']
    job.maintenance_type = mtype
    job.status = status
    job.starts_at = starts
    job.ends_at = ends
    job.estimated_completion = due or (ends.date() if ends else None)
    job.next_job_date = nxt
    job.schedule_note = note
    db.session.flush()
    return created
