from flask import Blueprint, jsonify, request
from sqlalchemy import or_

from api import auth as authn
from api import serializers as ser
from api.app import ApiError
from api.paging import paginate
from core.models import Defect, EquipmentType

bp = Blueprint('defects', __name__)


@bp.get('/defects')
@authn.require_master
def list_defects():
    q = Defect.query.filter(Defect.deleted_at.is_(None))
    if request.args.get('include_merged') not in ('1', 'true'):
        q = q.filter(Defect.merged_into_id.is_(None))
    if request.args.get('kind') in ('scheduled', 'unscheduled'):
        q = q.filter(Defect.kind == request.args['kind'])
    if request.args.get('status'):
        q = q.filter(Defect.status == request.args['status'])
    if request.args.get('type'):
        t = EquipmentType.query.filter_by(key=request.args['type']).first()
        if t is None:
            raise ApiError('Unknown equipment type', 400)
        q = q.filter(Defect.equipment_type_id == t.id)
    if request.args.get('q'):
        like = f"%{request.args['q'].strip()}%"
        q = q.filter(or_(Defect.title.ilike(like), Defect.description.ilike(like),
                         Defect.location.ilike(like), Defect.specific_equipment.ilike(like)))
    q = q.order_by(Defect.occurred_at.desc().nullslast(), Defect.id.desc())
    page = paginate(q)
    return jsonify({'items': [ser.defect(d) for d in page.pop('rows')], **page})


@bp.get('/defects/<int:defect_id>')
@authn.require_master
def get_defect(defect_id):
    d = Defect.query.get(defect_id)
    if d is None or d.deleted_at is not None:
        raise ApiError('Not found', 404)
    return jsonify(ser.defect(d, with_detail=True))
