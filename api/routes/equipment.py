from flask import Blueprint, jsonify, request

from api import auth as authn
from api import serializers as ser
from api.app import ApiError
from core import equipment

bp = Blueprint('equipment', __name__)


@bp.get('/equipment-types')
@authn.require_master
def list_types():
    return jsonify({'items': [ser.etype(t) for t in equipment.list_types(include_inactive=True)]})


@bp.post('/equipment-types')
@authn.require_master
def create_type():
    b = request.get_json(silent=True) or {}
    try:
        t = equipment.create_type(b.get('key'), b.get('name'), b.get('blurb'), b.get('emoji'))
    except equipment.EquipmentError as exc:
        raise ApiError(str(exc), 400)
    return jsonify(ser.etype(t)), 201


@bp.patch('/equipment-types/<int:type_id>')
@authn.require_master
def update_type(type_id):
    b = request.get_json(silent=True) or {}
    try:
        t = equipment.update_type(type_id, name=b.get('name'), blurb=b.get('blurb'), emoji=b.get('emoji'),
                                  active=b.get('active'), sort_order=b.get('sort_order'))
    except equipment.EquipmentError as exc:
        raise ApiError(str(exc), 400)
    return jsonify(ser.etype(t))
