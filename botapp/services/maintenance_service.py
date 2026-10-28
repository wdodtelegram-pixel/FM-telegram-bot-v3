"""
Maintenance job reads.

Ported from the API's services/maintenance_service.py. The bot only reads
maintenance work (it never creates, edits or deletes jobs), so the write side
and the role rules that guard it stay with the API.
"""

import datetime

from sqlalchemy import case, func, or_

from botapp.db import db
from botapp.fm import catalog
from botapp.models import MaintenanceJob


class MaintenanceError(Exception):
    """A request that is well-formed but cannot be satisfied (bad category)."""


def list_jobs(category=None, status=None, maintenance_type=None, building_id=None,
              technician_id=None, outstanding=None, overdue=None, search=None,
              limit=None):
    """
    Filtered job list, newest schedule first.

    Every filter is optional and independent. `overdue` compares the real date
    column against today, which the spreadsheet version could never do because
    it stored "Week 3 January 2026" as text.
    """
    query = MaintenanceJob.query

    if category:
        resolved = catalog.resolve_category(category)
        if not resolved:
            raise MaintenanceError(f'Unknown category: {category}')
        query = query.filter(MaintenanceJob.category == resolved)

    if status:
        canonical = catalog.STATUS_CANONICAL.get(status.strip().lower())
        if not canonical:
            raise MaintenanceError(f'Unknown status: {status}')
        query = query.filter(MaintenanceJob.status == canonical)

    if maintenance_type:
        canonical = catalog.TYPE_CANONICAL.get(maintenance_type.strip().lower())
        if not canonical:
            raise MaintenanceError(f'Unknown maintenance type: {maintenance_type}')
        query = query.filter(MaintenanceJob.maintenance_type == canonical)

    if building_id:
        query = query.filter(MaintenanceJob.building_id == building_id)

    if technician_id:
        query = query.filter(MaintenanceJob.assigned_technician_id == technician_id)

    if outstanding:
        query = query.filter(MaintenanceJob.status != catalog.STATUS_COMPLETED)

    if overdue:
        query = query.filter(
            MaintenanceJob.status != catalog.STATUS_COMPLETED,
            MaintenanceJob.estimated_completion.isnot(None),
            MaintenanceJob.estimated_completion < datetime.date.today(),
        )

    if search:
        like = f'%{search.strip()}%'
        query = query.filter(
            or_(
                MaintenanceJob.description.ilike(like),
                MaintenanceJob.location.ilike(like),
                MaintenanceJob.job_ref.ilike(like),
            )
        )

    query = query.order_by(
        MaintenanceJob.estimated_completion.asc().nullslast(),
        MaintenanceJob.job_ref.asc(),
    )

    if limit:
        query = query.limit(limit)

    return query.all()


def jobs_for_category(category_key, limit=None):
    """
    Jobs for one trade, unfinished work first.

    That ordering is what the chatbot's category_message did with a pandas sort,
    and it is what people open the bot to check.
    """
    resolved = catalog.resolve_category(category_key)
    if not resolved:
        raise MaintenanceError(f'Unknown category: {category_key}')

    order = case(
        (MaintenanceJob.status == catalog.STATUS_IN_PROGRESS, 0),
        (MaintenanceJob.status == catalog.STATUS_YET_TO_START, 1),
        (MaintenanceJob.status == catalog.STATUS_COMPLETED, 2),
        else_=3,
    )

    query = (
        MaintenanceJob.query
        .filter(MaintenanceJob.category == resolved)
        .order_by(order, MaintenanceJob.estimated_completion.asc().nullslast())
    )
    if limit:
        query = query.limit(limit)
    return query.all()


def summary_counts():
    """
    Per-trade status counts for the /service dashboard and the web summary row.

    One grouped query rather than a query per category, and every trade in the
    catalog appears even when it has no jobs, so the dashboard shape is stable.
    """
    rows = (
        db.session.query(
            MaintenanceJob.category,
            MaintenanceJob.status,
            func.count(MaintenanceJob.id),
        )
        .group_by(MaintenanceJob.category, MaintenanceJob.status)
        .all()
    )

    summary = {
        key: {
            'name': meta['name'],
            'emoji': meta['emoji'],
            'total': 0,
            catalog.STATUS_YET_TO_START: 0,
            catalog.STATUS_IN_PROGRESS: 0,
            catalog.STATUS_COMPLETED: 0,
        }
        for key, meta in catalog.CATEGORIES.items()
    }

    for category, status, count in rows:
        key = catalog.category_key(category)
        if key is None:
            # A category that is in the database but no longer in the catalog.
            # Counting it under a trade that no longer exists would be a lie.
            continue
        summary[key]['total'] += count
        if status in summary[key]:
            summary[key][status] += count

    return summary


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------
def calendar_entries(start, end):
    """
    Everything dated from `start` to `end` inclusive, soonest first.

    Returns (date, kind, job) tuples. `kind` is 'due' (an unfinished job's
    estimated completion) or 'next' (the next scheduled service, which still
    matters once the current job is completed). Only maintenance jobs have
    dates; defects do not.
    """
    due = (
        MaintenanceJob.query
        .filter(MaintenanceJob.status != catalog.STATUS_COMPLETED,
                MaintenanceJob.estimated_completion.isnot(None),
                MaintenanceJob.estimated_completion >= start,
                MaintenanceJob.estimated_completion <= end)
        .all()
    )
    nxt = (
        MaintenanceJob.query
        .filter(MaintenanceJob.next_job_date.isnot(None),
                MaintenanceJob.next_job_date >= start,
                MaintenanceJob.next_job_date <= end)
        .all()
    )
    entries = [(j.estimated_completion, 'due', j) for j in due]
    entries += [(j.next_job_date, 'next', j) for j in nxt]
    entries.sort(key=lambda e: (e[0], e[2].job_ref, e[1]))
    return entries


def overdue_entries(today):
    """Unfinished jobs whose estimated completion is before `today`, oldest first."""
    jobs = (
        MaintenanceJob.query
        .filter(MaintenanceJob.status != catalog.STATUS_COMPLETED,
                MaintenanceJob.estimated_completion.isnot(None),
                MaintenanceJob.estimated_completion < today)
        .order_by(MaintenanceJob.estimated_completion.asc(), MaintenanceJob.job_ref.asc())
        .all()
    )
    return [(j.estimated_completion, 'overdue', j) for j in jobs]
