from flask import Blueprint, g, jsonify, request

from api import auth as authn
from core import access
from core.models import BotMember

bp = Blueprint('access', __name__)


def _error(exc):
    from api.app import ApiError
    return ApiError(str(exc), 400)


@bp.get('/access/members')
@authn.require_master
def members():
    try:
        rows = access.list_members(request.args.get('status') or None)
    except access.AccessError as exc:
        raise _error(exc)
    return jsonify({'items': [access.serialize(m) for m in rows]})


def _act(fn, member_id, *args):
    try:
        return jsonify(fn(member_id, *args, by_member_id=g.member.id))
    except access.AccessError as exc:
        raise _error(exc)


@bp.post('/access/members/<int:member_id>/approve')
@authn.require_master
def approve(member_id):
    tier = (request.get_json(silent=True) or {}).get('tier', 'end_user')
    return _act(lambda mid, by_member_id: access.approve(mid, by_member_id, tier=tier), member_id)


@bp.post('/access/members/<int:member_id>/deny')
@authn.require_master
def deny(member_id):
    return _act(access.deny, member_id)


@bp.post('/access/members/<int:member_id>/revoke')
@authn.require_master
def revoke(member_id):
    return _act(access.revoke, member_id)


@bp.post('/access/members/<int:member_id>/reconsider')
@authn.require_master
def reconsider(member_id):
    return _act(access.reconsider, member_id)


@bp.patch('/access/members/<int:member_id>')
@authn.require_master
def update_member(member_id):
    body = request.get_json(silent=True) or {}
    try:
        out = None
        if 'tier' in body:
            out = access.set_tier(member_id, body['tier'], by_member_id=g.member.id)
        if 'user_id' in body:
            out = access.link_web_user(member_id, body['user_id'], by_member_id=g.member.id)
    except access.AccessError as exc:
        raise _error(exc)
    if out is None:
        member = BotMember.query.get(member_id)
        if member is None:
            raise _error(access.AccessError('No such member'))
        out = access.serialize(member)
    return jsonify(out)
