"""JSON shapes for the website. Datetimes are ISO strings in the data's own (local, naive) time."""

from core.fm import catalog


def iso(value):
    return value.isoformat() if value else None


def etype(t):
    return {'id': t.id, 'key': t.key, 'name': t.name, 'emoji': t.emoji, 'blurb': t.blurb,
            'sort_order': t.sort_order, 'active': t.active} if t else None


def scheduled(job):
    from core.models import EquipmentType
    t = EquipmentType.query.get(job.equipment_type_id) if job.equipment_type_id else None
    return {
        'id': job.id, 'job_ref': job.job_ref, 'type': etype(t), 'category': job.category,
        'description': job.description, 'location': job.location, 'status': job.status,
        'maintenance_type': job.maintenance_type,
        'starts_at': iso(job.starts_at), 'ends_at': iso(job.ends_at),
        'estimated_completion': iso(job.estimated_completion), 'next_job_date': iso(job.next_job_date),
        'schedule_note': job.schedule_note,
    }


def defect(d, with_detail=False):
    from core.models import EquipmentType, MaintenanceJob, Defect, DefectComment
    t = EquipmentType.query.get(d.equipment_type_id) if d.equipment_type_id else None
    job = MaintenanceJob.query.get(d.maintenance_job_id) if d.maintenance_job_id else None
    out = {
        'id': d.id, 'title': d.title, 'description': d.description, 'status': d.status,
        'priority': d.priority, 'kind': d.kind, 'type': etype(t), 'location': d.location,
        'specific_equipment': d.specific_equipment, 'occurred_at': iso(d.occurred_at),
        'created_at': iso(d.created_at), 'updated_at': iso(d.updated_at),
        'reporter': d.reporter_label, 'reported_via_bot': d.bot_reporter_id is not None,
        'scheduled_job': {'id': job.id, 'job_ref': job.job_ref, 'description': job.description} if job else None,
        'merged_into_id': d.merged_into_id,
        'merged_count': Defect.query.filter_by(merged_into_id=d.id).count(),
        'building': d.building.name if d.building else None,
    }
    if with_detail:
        out['comments'] = [{'id': c.id, 'text': c.initial_report, 'created_at': iso(c.created_at)}
                           for c in DefectComment.query.filter_by(defect_id=d.id)
                           .order_by(DefectComment.id).all() if c.initial_report]
        out['merged_reports'] = [
            {'id': m.id, 'description': m.description, 'reporter': m.reporter_label,
             'occurred_at': iso(m.occurred_at)}
            for m in Defect.query.filter_by(merged_into_id=d.id).order_by(Defect.id).all()]
        out['has_image'] = bool(d.initial_report_image)
    return out
