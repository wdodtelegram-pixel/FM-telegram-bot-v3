from flask import Blueprint, g, jsonify, request

from api import auth as authn
from api.app import ApiError

bp = Blueprint('auth', __name__)


@bp.get('/health')
def health():
    return jsonify({'status': 'ok'})


@bp.post('/auth/login')
def login():
    body = request.get_json(silent=True) or {}
    user, member = authn.authenticate(body.get('email'), body.get('password'))
    return jsonify({'token': authn.make_token(user, member),
                    'user': {'id': user.id, 'name': member.display_name, 'email': user.email,
                             'tier': member.tier}})


@bp.get('/auth/me')
@authn.require_master
def me():
    m = g.member
    return jsonify({'id': m.user_id, 'name': m.display_name, 'tier': m.tier, 'member_id': m.id})
