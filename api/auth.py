"""
Website sign-in: master control only.

A person signs in with the email and password of a row in `users` (the table
the web app has always used, bcrypt hashes), and only if that user is linked to
an APPROVED master_control member. End users have no website access at all.
Every request re-checks the member, so revoking someone takes effect on their
very next click, not when their token expires.
"""

import datetime
import functools

import jwt
from sqlalchemy import func
from flask import current_app, g, request

from api.app import ApiError
from core.models import BotMember, User
from core.passwords import check_password


def master_member_for_user(user_id):
    return BotMember.query.filter_by(user_id=user_id, status='approved', tier='master_control').first()


def authenticate(email, password):
    """The (user, member) for valid credentials of a master control member, else raises ApiError."""
    user = User.query.filter(func.lower(User.email) == (email or '').strip().lower()).first()
    # The same message for every failure, so the form does not reveal which emails exist.
    bad = ApiError('Incorrect email or password.', 401)
    if user is None or not check_password(password or '', user.password_hash):
        raise bad
    member = master_member_for_user(user.id)
    if member is None:
        raise ApiError('This account does not have website access. Ask master control.', 403)
    return user, member


def make_token(user, member):
    now = datetime.datetime.now(datetime.timezone.utc)
    payload = {'sub': str(user.id), 'member': member.id, 'name': member.display_name,
               'iat': now, 'exp': now + datetime.timedelta(hours=current_app.config['JWT_HOURS'])}
    return jwt.encode(payload, current_app.config['SECRET_KEY'], algorithm='HS256')


def require_master(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        header = request.headers.get('Authorization', '')
        if not header.startswith('Bearer '):
            raise ApiError('Please sign in.', 401)
        try:
            claims = jwt.decode(header[7:], current_app.config['SECRET_KEY'], algorithms=['HS256'])
        except jwt.ExpiredSignatureError:
            raise ApiError('Your session has expired. Please sign in again.', 401)
        except jwt.InvalidTokenError:
            raise ApiError('Please sign in.', 401)
        member = master_member_for_user(int(claims['sub']))
        if member is None:
            raise ApiError('Your website access has been withdrawn.', 403)
        g.member = member
        return fn(*args, **kwargs)
    return wrapper
