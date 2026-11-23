r"""
Access: who may use the bot and the website, and how that is decided.

One row per Telegram chat in bot_members, so a decision is remembered and
nobody has to ask twice:

    (no row) --request--> pending --approve--> approved <--> revoked
                              \--deny--> denied --reconsider--> pending/approved

Tiers: end_user (Telegram only) and master_control (Telegram and website).
Only master control decides. The last approved master control can never be
revoked or demoted, so the system cannot lock itself out.
"""

import datetime

from core.db import db
from core.models import ACCESS_STATUSES, TIERS, BotMember


class AccessError(Exception):
    """A request the access rules refuse (not allowed, no such member, last master)."""


def serialize(m):
    return {'id': m.id, 'chat_id': m.telegram_chat_id, 'username': m.telegram_username,
            'name': m.display_name, 'tier': m.tier, 'status': m.status, 'user_id': m.user_id,
            'requested_at': m.requested_at.isoformat() if m.requested_at else None,
            'decided_at': m.decided_at.isoformat() if m.decided_at else None}


def by_chat(chat_id):
    return BotMember.query.filter_by(telegram_chat_id=chat_id).first()


def state_for_chat(chat_id):
    """'none' | 'pending' | 'approved' | 'denied' | 'revoked'."""
    m = by_chat(chat_id)
    return m.status if m else 'none'


def request_access(chat_id, username, display_name):
    """
    The one request a person gets. Returns (state, member_dict):
    'requested' (a new pending request was just stored), or the existing state
    ('pending' | 'approved' | 'denied' | 'revoked') with nothing changed. A
    denied or revoked person cannot re-request; master control can reconsider.
    """
    m = by_chat(chat_id)
    if m is not None:
        return m.status, serialize(m)
    now = datetime.datetime.utcnow()
    m = BotMember(telegram_chat_id=chat_id, telegram_username=username,
                  display_name=(display_name or username or f'chat {chat_id}')[:80],
                  tier='end_user', status='pending', requested_at=now)
    db.session.add(m)
    db.session.commit()
    return 'requested', serialize(m)


def _acting(by_member_id):
    """The deciding member, or None for the command line (trusted: it has the database)."""
    if by_member_id is None:
        return None
    actor = BotMember.query.get(by_member_id)
    if actor is None or not actor.is_master:
        raise AccessError('Only master control can do that')
    return actor


def _masters_left_after(member):
    return BotMember.query.filter(BotMember.status == 'approved', BotMember.tier == 'master_control',
                                  BotMember.id != member.id).count()


def _load(member_id):
    m = BotMember.query.get(member_id)
    if m is None:
        raise AccessError('No such member')
    return m


def approve(member_id, by_member_id=None, tier='end_user'):
    if tier not in TIERS:
        raise AccessError(f'tier must be one of: {", ".join(TIERS)}')
    by = _acting(by_member_id)
    m = _load(member_id)
    if m.status == 'approved' and m.tier == tier:
        return serialize(m)
    m.status, m.tier = 'approved', tier
    m.decided_by, m.decided_at = (by.id if by else None), datetime.datetime.utcnow()
    db.session.commit()
    return serialize(m)


def deny(member_id, by_member_id=None):
    by = _acting(by_member_id)
    m = _load(member_id)
    if m.status == 'approved':
        raise AccessError('That person is already approved; revoke them instead')
    m.status = 'denied'
    m.decided_by, m.decided_at = (by.id if by else None), datetime.datetime.utcnow()
    db.session.commit()
    return serialize(m)


def revoke(member_id, by_member_id=None):
    by = _acting(by_member_id)
    m = _load(member_id)
    if m.is_master and _masters_left_after(m) == 0:
        raise AccessError('That is the last master control; make someone else master control first')
    m.status = 'revoked'
    m.decided_by, m.decided_at = (by.id if by else None), datetime.datetime.utcnow()
    db.session.commit()
    return serialize(m)


def reconsider(member_id, by_member_id=None):
    """Put a denied or revoked person back to pending so they can be decided again."""
    by = _acting(by_member_id)
    m = _load(member_id)
    if m.status not in ('denied', 'revoked'):
        raise AccessError('Only denied or revoked people can be reconsidered')
    m.status = 'pending'
    m.decided_by, m.decided_at = (by.id if by else None), datetime.datetime.utcnow()
    db.session.commit()
    return serialize(m)


def set_tier(member_id, tier, by_member_id=None):
    if tier not in TIERS:
        raise AccessError(f'tier must be one of: {", ".join(TIERS)}')
    by = _acting(by_member_id)
    m = _load(member_id)
    if m.is_master and tier != 'master_control' and _masters_left_after(m) == 0:
        raise AccessError('That is the last master control; make someone else master control first')
    m.tier = tier
    m.decided_by, m.decided_at = (by.id if by else None), datetime.datetime.utcnow()
    db.session.commit()
    return serialize(m)


def link_web_user(member_id, web_user_id, by_member_id=None):
    """Map a member to a web account (needed for website sign-in and 'assigned to me')."""
    from core.models import User
    _acting(by_member_id)
    m = _load(member_id)
    if web_user_id is not None and not User.query.get(web_user_id):
        raise AccessError(f'No web user with id {web_user_id}')
    m.user_id = web_user_id
    db.session.commit()
    return serialize(m)


def list_members(status=None):
    q = BotMember.query
    if status:
        if status not in ACCESS_STATUSES:
            raise AccessError('Unknown status')
        q = q.filter_by(status=status)
    return q.order_by(BotMember.requested_at.desc().nullslast(), BotMember.id.desc()).all()


def masters():
    return BotMember.query.filter_by(status='approved', tier='master_control').all()
