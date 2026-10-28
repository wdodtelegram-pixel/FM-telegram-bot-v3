"""
Defect queries and creation.

Ported from the API's services/defect_service.py with one structural change:
the acting person is a botapp.actor.Actor, not a users row. A member who is not
mapped to a web account has no users row, so a defect they raise is recorded with
`bot_reporter_id` + `reporter_label` instead of `reporter_id`.
"""

from botapp.db import db
from botapp.models import Building, Defect, DefectComment

OPEN_STATUSES = ('Open', 'Reviewed', 'Ongoing', 'Done')

PRIORITIES = ('low', 'medium', 'high')


class DefectError(Exception):
    """A defect request that is well-formed but cannot be satisfied."""


def list_visible_defects(actor, only_open=True, assigned_only=False, limit=25):
    """
    Defects, newest first, capped at `limit`. There are no roles: every member
    sees every open defect. `assigned_only` (/mydefects) narrows to the web
    account the member is mapped to.

    A member with no mapped web account has nothing assigned to them. That is
    handled explicitly: `assigned_technician_id == None` would compile to
    IS NULL and quietly return every unassigned defect.
    """
    query = Defect.query.filter(Defect.deleted_at.is_(None))

    if assigned_only:
        if actor.user_id is None:
            return []
        query = query.filter(Defect.assigned_technician_id == actor.user_id)

    if only_open:
        query = query.filter(Defect.status.in_(OPEN_STATUSES))

    return query.order_by(Defect.updated_at.desc(), Defect.id.desc()).limit(limit).all()


def create_defect(actor, title, description, building_id, priority,
                  initial_report=None, initial_report_image=None):
    """Raise a defect on behalf of `actor`. Same validation as POST /api/defects."""
    title = (title or '').strip()
    description = (description or '').strip()
    if not title:
        raise DefectError('A defect needs a title')
    if not description:
        raise DefectError('A defect needs a description')

    priority = (priority or '').strip().lower()
    if priority not in PRIORITIES:
        raise DefectError(f"Priority must be one of: {', '.join(PRIORITIES)}")

    building = Building.query.get(building_id)
    if not building:
        raise DefectError('Building not found')

    defect = Defect(
        title=title,
        description=description,
        priority=priority,
        building_id=building.id,
        # A mapped member is attributed to their web account so the website's
        # per-user views keep working; everyone else is a bot reporter.
        reporter_id=actor.user_id,
        bot_reporter_id=None if actor.user_id else actor.member_id,
        reporter_label=actor.name,
        initial_report_image=initial_report_image,
    )
    db.session.add(defect)
    db.session.flush()

    db.session.add(DefectComment(defect_id=defect.id, initial_report=initial_report or None))
    db.session.commit()
    return defect


def buildings_for_picker(limit=50):
    """Buildings to offer in the /report inline keyboard."""
    return Building.query.order_by(Building.name.asc()).limit(limit).all()
