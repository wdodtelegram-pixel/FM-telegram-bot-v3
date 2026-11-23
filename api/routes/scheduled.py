import datetime

from flask import Blueprint, jsonify, request
from sqlalchemy import and_, func, or_

from api import auth as authn
from api import serializers as ser
from api.app import ApiError
from api.paging import paginate
from core import importer
from core.models import Defect, EquipmentType, MaintenanceJob
from core.when import parse_range

bp = Blueprint('scheduled', __name__)


@bp.get('/scheduled')
@authn.require_master
def list_scheduled():
    q = MaintenanceJob.query
    if request.args.get('type'):
        t = EquipmentType.query.filter_by(key=request.args['type']).first()
        if t is None:
            raise ApiError('Unknown equipment type', 400)
        q = q.filter(MaintenanceJob.equipment_type_id == t.id)
    if request.args.get('status'):
        q = q.filter(MaintenanceJob.status == request.args['status'])
    if request.args.get('q'):
        like = f"%{request.args['q'].strip()}%"
        q = q.filter(or_(MaintenanceJob.description.ilike(like), MaintenanceJob.location.ilike(like),
                         MaintenanceJob.job_ref.ilike(like)))
    if request.args.get('from') or request.args.get('to'):
        lo_hi = parse_range(f"{request.args.get('from', request.args.get('to'))} - "
                            f"{request.args.get('to', request.args.get('from'))}", datetime.date.today())
        if lo_hi is None:
            raise ApiError('Could not read the dates (use YYYY-MM-DD)', 400)
        lo, hi = lo_hi
        has_tl = or_(MaintenanceJob.starts_at.isnot(None), MaintenanceJob.ends_at.isnot(None))
        q = q.filter(or_(
            and_(has_tl, func.coalesce(MaintenanceJob.starts_at, MaintenanceJob.ends_at) <= hi,
                 func.coalesce(MaintenanceJob.ends_at, MaintenanceJob.starts_at) >= lo),
            and_(~has_tl,
                 func.coalesce(MaintenanceJob.next_job_date, MaintenanceJob.estimated_completion) >= lo.date(),
                 func.coalesce(MaintenanceJob.next_job_date, MaintenanceJob.estimated_completion) <= hi.date())))
    q = q.order_by(func.coalesce(MaintenanceJob.starts_at, MaintenanceJob.ends_at).asc().nullslast(),
                   MaintenanceJob.job_ref.asc())
    page = paginate(q)
    return jsonify({'items': [ser.scheduled(j) for j in page.pop('rows')], **page})


@bp.get('/scheduled/<int:job_id>')
@authn.require_master
def get_scheduled(job_id):
    job = MaintenanceJob.query.get(job_id)
    if job is None:
        raise ApiError('Not found', 404)
    out = ser.scheduled(job)
    out['reports'] = [ser.defect(d) for d in
                      Defect.query.filter_by(maintenance_job_id=job.id).order_by(Defect.id.desc()).limit(50)]
    return jsonify(out)


@bp.post('/scheduled/import')
@authn.require_master
def import_scheduled():
    upload = request.files.get('file')
    if upload is None:
        raise ApiError('Choose a CSV file to import.', 400)
    try:
        text = upload.read().decode('utf-8-sig')
    except UnicodeDecodeError:
        raise ApiError('The file is not UTF-8 text. Save it as "CSV UTF-8" and try again.', 400)
    dry = (request.form.get('dry_run') or '').lower() in ('1', 'true', 'yes')
    result = importer.import_csv(text, dry_run=dry)
    return jsonify({'created': result.created, 'updated': result.updated, 'dry_run': dry,
                    'skipped': [{'line': line, 'reason': reason} for line, reason in result.skipped]})
