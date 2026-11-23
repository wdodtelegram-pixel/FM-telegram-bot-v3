import datetime

from flask import Blueprint, jsonify
from sqlalchemy import func, or_

from api import auth as authn
from core import config
from core.db import db
from core.fm import catalog
from core.models import BotMember, Defect, EquipmentType, MaintenanceJob

bp = Blueprint('dashboard', __name__)


@bp.get('/dashboard')
@authn.require_master
def dashboard():
    now = config.now()
    today = now.date()
    start = datetime.datetime.combine(today, datetime.time())
    week_end = start + datetime.timedelta(days=7)
    day_end = start + datetime.timedelta(days=1)
    open_jobs = MaintenanceJob.status != catalog.STATUS_COMPLETED

    def overlapping(lo, hi):
        return MaintenanceJob.query.filter(
            or_(func.coalesce(MaintenanceJob.starts_at, MaintenanceJob.ends_at) < hi,
                MaintenanceJob.starts_at.is_(None)),
            func.coalesce(MaintenanceJob.ends_at, MaintenanceJob.starts_at) >= lo,
            MaintenanceJob.starts_at.isnot(None) | MaintenanceJob.ends_at.isnot(None)).count()

    by_type = []
    for t in EquipmentType.query.filter_by(active=True).order_by(EquipmentType.sort_order, EquipmentType.id):
        total = MaintenanceJob.query.filter_by(equipment_type_id=t.id).count()
        open_n = MaintenanceJob.query.filter(MaintenanceJob.equipment_type_id == t.id, open_jobs).count()
        reports = Defect.query.filter(Defect.equipment_type_id == t.id, Defect.merged_into_id.is_(None),
                                      Defect.deleted_at.is_(None)).count()
        by_type.append({'key': t.key, 'name': t.name, 'emoji': t.emoji, 'scheduled_total': total,
                        'scheduled_open': open_n, 'reports': reports})

    reports = Defect.query.filter(Defect.deleted_at.is_(None), Defect.merged_into_id.is_(None))
    status_counts = dict(db.session.query(Defect.status, func.count(Defect.id))
                         .filter(Defect.deleted_at.is_(None), Defect.merged_into_id.is_(None))
                         .group_by(Defect.status).all())
    access_counts = dict(db.session.query(BotMember.status, func.count(BotMember.id))
                         .group_by(BotMember.status).all())
    return jsonify({
        'scheduled': {
            'total': MaintenanceJob.query.count(),
            'today': overlapping(start, day_end),
            'next_7_days': overlapping(start, week_end),
            'overdue': MaintenanceJob.query.filter(
                open_jobs, MaintenanceJob.estimated_completion.isnot(None),
                MaintenanceJob.estimated_completion < today).count(),
            'by_type': by_type,
        },
        'reports': {
            'total': reports.count(),
            'open': reports.filter(Defect.status.in_(('Open', 'Reviewed', 'Ongoing', 'Done'))).count(),
            'scheduled': reports.filter(Defect.kind == 'scheduled').count(),
            'unscheduled': reports.filter(Defect.kind == 'unscheduled').count(),
            'added_to_existing': Defect.query.filter(Defect.merged_into_id.isnot(None)).count(),
            'last_7_days': reports.filter(Defect.created_at >= now - datetime.timedelta(days=7)).count(),
            'by_status': status_counts,
        },
        'access': {
            'pending': access_counts.get('pending', 0), 'approved': access_counts.get('approved', 0),
            'denied': access_counts.get('denied', 0), 'revoked': access_counts.get('revoked', 0),
            'master_control': BotMember.query.filter_by(status='approved', tier='master_control').count(),
        },
    })
