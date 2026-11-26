"""
Administration from the command line. This is how the allowlist is managed.

    python -m botapp.admin add CHAT_ID "Name" [--master] [--web-user USER_ID]
    python -m botapp.admin requests                      # pending access requests
    python -m botapp.admin approve CHAT_ID [--master]    # approve a request
    python -m botapp.admin deny CHAT_ID
    python -m botapp.admin revoke CHAT_ID
    python -m botapp.admin set-tier CHAT_ID end_user|master_control
    python -m botapp.admin remove CHAT_ID
    python -m botapp.admin members
    python -m botapp.admin link-user CHAT_ID USER_ID     # or --clear
    python -m botapp.admin web-login CHAT_ID EMAIL       # give a master control member a website login
    python -m botapp.admin first-run                     # fresh install: choose the first admin's login, get a code
    python -m botapp.admin setup-status                  # exit 0 if a master control exists, else 1
    python -m botapp.admin import-csv FILE [--dry-run]   # load scheduled items/events
    python -m botapp.admin types                         # list equipment types
    python -m botapp.admin add-type KEY "Name" [--emoji X] [--blurb T]
    python -m botapp.admin edit-type KEY [--name N] [--emoji X] [--blurb T] [--disable|--enable]

CHAT_ID is the person's Telegram ID. They can find it by sending /start to the
bot, which replies with it even when they are not yet allowed.

--web-user maps the person to a web-app account (a row in `users`). It is only
needed for "assigned to me": /myjobs, /mydefects and assignment alerts.
"""

import argparse
import datetime
import sys

from sqlalchemy import func

from core import db as dbmod
from core import access, equipment, importer, passwords, setup
from core.db import Session, db
from core.models import TIERS, BotMember, User


class AdminError(Exception):
    pass


def add_member(chat_id, name, web_user=None, username=None, tier='end_user'):
    if BotMember.query.filter_by(telegram_chat_id=chat_id).first():
        raise AdminError(f'{chat_id} is already on the allowlist')
    if web_user is not None and not User.query.get(web_user):
        raise AdminError(f'no web user with id {web_user} (see: SELECT id, name FROM users)')
    if tier not in TIERS:
        raise AdminError(f'tier must be one of: {", ".join(TIERS)}')
    now = datetime.datetime.utcnow()
    member = BotMember(telegram_chat_id=chat_id, display_name=name.strip(),
                       telegram_username=username, user_id=web_user,
                       tier=tier, status='approved', requested_at=now, decided_at=now)
    db.session.add(member)
    db.session.commit()
    return member.id


def remove_member(chat_id):
    member = BotMember.query.filter_by(telegram_chat_id=chat_id).first()
    if member is None:
        return False
    db.session.delete(member)
    db.session.commit()
    return True


def create_web_login(chat_id, email, password, reset=False):
    """
    Give an approved master control member a website login (a row in `users`).
    Returns 'created' | 'linked' | 'reset'. An existing user is linked; its
    password changes only with reset=True.
    """
    member = access.by_chat(chat_id)
    if member is None or member.status != 'approved' or member.tier != 'master_control':
        raise AdminError(f'{chat_id} is not an approved master control member')
    email = (email or '').strip().lower()
    if '@' not in email:
        raise AdminError('Give a valid email address')
    user = User.query.filter(func.lower(User.email) == email).first()
    if user is None:
        if len(password or '') < passwords.MIN_LENGTH:
            raise AdminError(f'The password must be at least {passwords.MIN_LENGTH} characters')
        user = User(name=member.display_name, email=email, role='admin',
                    password_hash=passwords.hash_password(password))
        db.session.add(user)
        db.session.flush()
        outcome = 'created'
    elif reset:
        if len(password or '') < passwords.MIN_LENGTH:
            raise AdminError(f'The password must be at least {passwords.MIN_LENGTH} characters')
        user.password_hash = passwords.hash_password(password)
        outcome = 'reset'
    else:
        outcome = 'linked'
    member.user_id = user.id
    db.session.commit()
    return outcome


def link_user(chat_id, web_user):
    """Map a member to a web account, or unmap with web_user=None."""
    member = BotMember.query.filter_by(telegram_chat_id=chat_id).first()
    if member is None:
        raise AdminError(f'{chat_id} is not on the allowlist')
    if web_user is not None and not User.query.get(web_user):
        raise AdminError(f'no web user with id {web_user}')
    member.user_id = web_user
    db.session.commit()


def main(argv=None):
    parser = argparse.ArgumentParser(prog='botapp.admin', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('add'); p.add_argument('chat_id', type=int); p.add_argument('name')
    p.add_argument('--web-user', type=int)
    p.add_argument('--master', action='store_true', help='master control: full access, Telegram and website')
    p = sub.add_parser('remove'); p.add_argument('chat_id', type=int)
    sub.add_parser('members')
    sub.add_parser('requests')
    p = sub.add_parser('approve'); p.add_argument('chat_id', type=int); p.add_argument('--master', action='store_true')
    p = sub.add_parser('deny'); p.add_argument('chat_id', type=int)
    p = sub.add_parser('revoke'); p.add_argument('chat_id', type=int)
    p = sub.add_parser('set-tier'); p.add_argument('chat_id', type=int); p.add_argument('tier', choices=TIERS)
    p = sub.add_parser('import-csv'); p.add_argument('file'); p.add_argument('--dry-run', action='store_true')
    sub.add_parser('types')
    p = sub.add_parser('add-type'); p.add_argument('key'); p.add_argument('name')
    p.add_argument('--emoji'); p.add_argument('--blurb')
    p = sub.add_parser('edit-type'); p.add_argument('key'); p.add_argument('--name')
    p.add_argument('--emoji'); p.add_argument('--blurb')
    g = p.add_mutually_exclusive_group(); g.add_argument('--disable', action='store_true'); g.add_argument('--enable', action='store_true')
    sub.add_parser('first-run')
    sub.add_parser('setup-status')
    p = sub.add_parser('web-login'); p.add_argument('chat_id', type=int); p.add_argument('email')
    p.add_argument('--reset', action='store_true', help='also reset the password of an existing user')
    p = sub.add_parser('link-user'); p.add_argument('chat_id', type=int)
    p.add_argument('user_id', type=int, nargs='?'); p.add_argument('--clear', action='store_true')

    args = parser.parse_args(argv)
    if not dbmod.is_bound():          # tests bind the session to their own transaction first
        dbmod.init_engine()

    try:
        if args.cmd == 'add':
            add_member(args.chat_id, args.name, args.web_user,
                       tier='master_control' if args.master else 'end_user')
            print(f'added {args.name} ({args.chat_id})')
        elif args.cmd == 'remove':
            print('removed' if remove_member(args.chat_id) else 'not on the allowlist')
        elif args.cmd in ('members', 'requests'):
            rows = access.list_members('pending' if args.cmd == 'requests' else None)
            for m in rows:
                print(f'{m.telegram_chat_id:>14}  {m.display_name:<24} {m.tier:<15} {m.status:<9} '
                      f'web user {m.user_id or "-"}')
            if not rows:
                print('none')
        elif args.cmd in ('approve', 'deny', 'revoke', 'set-tier'):
            m = access.by_chat(args.chat_id)
            if m is None:
                raise AdminError(f'{args.chat_id} has not asked for access (and is not on the list)')
            if args.cmd == 'approve':
                access.approve(m.id, tier='master_control' if args.master else 'end_user')
            elif args.cmd == 'deny':
                access.deny(m.id)
            elif args.cmd == 'revoke':
                access.revoke(m.id)
            else:
                access.set_tier(m.id, args.tier)
            print('done (the person is told by the bot within 30 seconds)')
        elif args.cmd == 'setup-status':
            done = setup.master_exists()
            print('set up' if done else 'not set up')
            raise SystemExit(0 if done else 1)
        elif args.cmd == 'first-run':
            if setup.master_exists():
                print('This system is already set up. Sign in at the website; approve people there or in Telegram.')
            else:
                import getpass
                email = input('Email for the website login: ').strip()
                pw = getpass.getpass(f'Password ({passwords.MIN_LENGTH}+ characters, not shown): ')
                if getpass.getpass('Again: ') != pw:
                    raise AdminError('The two passwords did not match')
                code = setup.create_claim(email, pw)
                print('\n' + '=' * 56)
                print('  Almost done. In Telegram, open YOUR bot and send:\n')
                print(f'      /claim {code}\n')
                print('  The first person to send it becomes master control.')
                print('  The code works once and expires in 24 hours.')
                print('=' * 56)
        elif args.cmd == 'web-login':
            import getpass
            pw = getpass.getpass('Password for the website login (not shown): ')
            if getpass.getpass('Again: ') != pw:
                raise AdminError('The two passwords did not match')
            print(f'website login {create_web_login(args.chat_id, args.email, pw, reset=args.reset)}')
        elif args.cmd == 'link-user':
            if args.clear == (args.user_id is not None):
                parser.error('give a USER_ID, or --clear')
            link_user(args.chat_id, None if args.clear else args.user_id)
            print('updated')
        elif args.cmd == 'import-csv':
            res = importer.import_csv(args.file, dry_run=args.dry_run)
            print(res.summary())
            for line, reason in res.skipped[:50]:
                print(f'  line {line}: {reason}')
            if len(res.skipped) > 50:
                print(f'  ... and {len(res.skipped) - 50} more')
        elif args.cmd == 'types':
            for t in equipment.list_types(include_inactive=True):
                print(f'{t.key:<14} {t.name:<24} {t.emoji or "":<3} {"" if t.active else "(disabled)"}')
        elif args.cmd == 'add-type':
            t = equipment.create_type(args.key, args.name, args.blurb, args.emoji)
            print(f'added {t.name} ({t.key})')
        elif args.cmd == 'edit-type':
            t = equipment.get_by_key_or_name(args.key)
            if t is None:
                raise AdminError(f'no equipment type "{args.key}"')
            equipment.update_type(t.id, name=args.name, blurb=args.blurb, emoji=args.emoji,
                                  active=False if args.disable else (True if args.enable else None))
            print('updated')
    except (AdminError, equipment.EquipmentError, access.AccessError, setup.SetupError) as exc:
        print(f'error: {exc}', file=sys.stderr)
        raise SystemExit(1)
    finally:
        Session.remove()


if __name__ == '__main__':
    main()
