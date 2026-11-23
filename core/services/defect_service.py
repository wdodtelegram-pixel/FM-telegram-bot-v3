"""
Defect queries and creation.

Ported from the API's services/defect_service.py with one structural change:
the acting person is a core.actor.Actor, not a users row. A member who is not
mapped to a web account has no users row, so a defect they raise is recorded with
`bot_reporter_id` + `reporter_label` instead of `reporter_id`.
"""

from core.models import Defect

OPEN_STATUSES = ('Open', 'Reviewed', 'Ongoing', 'Done')

def list_visible_defects(actor, only_open=True, assigned_only=False, limit=25):
    """
    Defects, newest first, capped at `limit`. There are no roles: every member
    sees every open defect. `assigned_only` (/mydefects) narrows to the web
    account the member is mapped to.

    A member with no mapped web account has nothing assigned to them. That is
    handled explicitly: `assigned_technician_id == None` would compile to
    IS NULL and quietly return every unassigned defect.
    """
    # Reports added to an existing report (merged_into_id) are not listed on their own.
    query = Defect.query.filter(Defect.deleted_at.is_(None), Defect.merged_into_id.is_(None))

    if assigned_only:
        if actor.user_id is None:
            return []
        query = query.filter(Defect.assigned_technician_id == actor.user_id)

    if only_open:
        query = query.filter(Defect.status.in_(OPEN_STATUSES))

    return query.order_by(Defect.updated_at.desc(), Defect.id.desc()).limit(limit).all()
