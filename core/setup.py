"""
First-run setup: how the very first master control is created on a fresh install.

Everything after the first master control is the normal request/approve flow
(core/access.py). The first one cannot be approved by anybody, so:

  1. the launcher (or `python -m botapp.admin first-run`) asks for an email and a
     password and calls create_claim(); it prints a one-time CODE;
  2. the person sends `/claim CODE` to their own bot; claim() makes that chat
     master control and creates their website login.

Only hashes are stored. The code is single-use, expires after 24 hours, locks
after MAX_ATTEMPTS wrong guesses, and stops working the moment any master
control exists, so it cannot be used to take over a running system.
"""

import datetime
import hashlib
import secrets

from sqlalchemy import func

from core import access
from core.db import db
from core.models import BotMember, SetupClaim, User
from core.passwords import MIN_LENGTH, check_password, hash_password

CODE_ALPHABET = '23456789ABCDEFGHJKLMNPQRSTUVWXYZ'     # no 0/O/1/I: it is read off one screen and typed into another
CODE_LENGTH = 10
TTL = datetime.timedelta(hours=24)
MAX_ATTEMPTS = 10


class SetupError(Exception):
    """A setup request that cannot be satisfied; the message is safe to show the user."""


def master_exists():
    return BotMember.query.filter_by(status='approved', tier='master_control').count() > 0


def _normalise(code):
    return ''.join(ch for ch in (code or '').upper() if ch.isalnum())


def _hash(code):
    return hashlib.sha256(_normalise(code).encode('utf-8')).hexdigest()


def format_code(raw):
    return f'{raw[:5]}-{raw[5:]}'


def create_claim(email, password):
    """Store a pending setup and return the one-time code (shown once, never stored)."""
    email = (email or '').strip().lower()
    if '@' not in email or '.' not in email.split('@')[-1]:
        raise SetupError('Please give a valid email address.')
    if len(password or '') < MIN_LENGTH:
        raise SetupError(f'The password must be at least {MIN_LENGTH} characters.')
    if master_exists():
        raise SetupError('This system is already set up.')
    if User.query.filter(func.lower(User.email) == email).first():
        raise SetupError('That email already has a website login. Use another, or sign in with it.')

    SetupClaim.query.filter(SetupClaim.claimed_at.is_(None)).delete(synchronize_session=False)
    raw = ''.join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
    now = datetime.datetime.utcnow()
    db.session.add(SetupClaim(code_hash=_hash(raw), email=email, password_hash=hash_password(password),
                              created_at=now, expires_at=now + TTL))
    db.session.commit()
    return format_code(raw)


def claim(chat_id, username, display_name, code):
    """
    Turn this chat into the first master control. Returns {'name', 'email'}.
    Raises SetupError with a message safe to show.
    """
    if master_exists():
        raise SetupError('This system is already set up.')
    now = datetime.datetime.utcnow()
    pending = (SetupClaim.query.filter(SetupClaim.claimed_at.is_(None))
               .order_by(SetupClaim.id.desc()).first())
    if pending is None or pending.expires_at <= now:
        raise SetupError('No setup is waiting (or it has expired). Run the launcher again to get a new code.')
    if pending.attempts >= MAX_ATTEMPTS:
        raise SetupError('Too many wrong codes. Run the launcher again to get a new code.')
    if not secrets.compare_digest(pending.code_hash, _hash(code)):
        pending.attempts += 1
        db.session.commit()
        left = MAX_ATTEMPTS - pending.attempts
        raise SetupError(f'That code is not right ({left} attempt{"s" if left != 1 else ""} left).')

    name = (display_name or username or f'chat {chat_id}')[:80]
    user = User(name=name, email=pending.email, role='admin', password_hash=pending.password_hash)
    db.session.add(user)
    db.session.flush()

    member = access.by_chat(chat_id)
    if member is None:
        member = BotMember(telegram_chat_id=chat_id, telegram_username=username, display_name=name,
                           joined_at=now, requested_at=now)
        db.session.add(member)
    member.tier, member.status = 'master_control', 'approved'
    member.user_id = user.id
    member.decided_at = now
    member.notified_status = 'approved'
    db.session.flush()

    pending.claimed_at = now
    pending.claimed_by_member_id = member.id
    db.session.commit()
    return {'name': name, 'email': pending.email}
