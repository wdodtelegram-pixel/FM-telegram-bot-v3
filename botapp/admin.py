"""
Administration from the command line. This is how the allowlist is managed.

    python -m botapp.admin add CHAT_ID "Name" [--web-user USER_ID]
    python -m botapp.admin remove CHAT_ID
    python -m botapp.admin members
    python -m botapp.admin link-user CHAT_ID USER_ID     # or --clear
    python -m botapp.admin import-links                  # carry over the old web /link bindings

CHAT_ID is the person's Telegram ID. They can find it by sending /start to the
bot, which replies with it even when they are not yet allowed.

--web-user maps the person to a web-app account (a row in `users`). It is only
needed for "assigned to me": /myjobs, /mydefects and assignment alerts.
"""

import argparse
import sys

from sqlalchemy import text

from botapp import db as dbmod
from botapp.db import Session, db
from botapp.models import BotMember, User


class AdminError(Exception):
    pass


def add_member(chat_id, name, web_user=None, username=None):
    if BotMember.query.filter_by(telegram_chat_id=chat_id).first():
        raise AdminError(f'{chat_id} is already on the allowlist')
    if web_user is not None and not User.query.get(web_user):
        raise AdminError(f'no web user with id {web_user} (see: SELECT id, name FROM users)')
    member = BotMember(telegram_chat_id=chat_id, display_name=name.strip(),
                       telegram_username=username, user_id=web_user)
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


def link_user(chat_id, web_user):
    """Map a member to a web account, or unmap with web_user=None."""
    member = BotMember.query.filter_by(telegram_chat_id=chat_id).first()
    if member is None:
        raise AdminError(f'{chat_id} is not on the allowlist')
    if web_user is not None and not User.query.get(web_user):
        raise AdminError(f'no web user with id {web_user}')
    member.user_id = web_user
    db.session.commit()


def import_links():
    """Allow everyone who linked through the web app's old flow, mapped to their account."""
    rows = db.session.execute(text(
        "SELECT id, name, telegram_chat_id, telegram_username FROM users "
        "WHERE telegram_chat_id IS NOT NULL")).all()
    created = 0
    for uid, name, chat_id, username in rows:
        if BotMember.query.filter_by(telegram_chat_id=chat_id).first():
            continue
        db.session.add(BotMember(telegram_chat_id=chat_id, telegram_username=username,
                                 display_name=name, user_id=uid))
        created += 1
    db.session.commit()
    return created


def main(argv=None):
    parser = argparse.ArgumentParser(prog='botapp.admin', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('add'); p.add_argument('chat_id', type=int); p.add_argument('name')
    p.add_argument('--web-user', type=int)
    p = sub.add_parser('remove'); p.add_argument('chat_id', type=int)
    sub.add_parser('members')
    sub.add_parser('import-links')
    p = sub.add_parser('link-user'); p.add_argument('chat_id', type=int)
    p.add_argument('user_id', type=int, nargs='?'); p.add_argument('--clear', action='store_true')

    args = parser.parse_args(argv)
    dbmod.init_engine()

    try:
        if args.cmd == 'add':
            add_member(args.chat_id, args.name, args.web_user)
            print(f'added {args.name} ({args.chat_id})')
        elif args.cmd == 'remove':
            print('removed' if remove_member(args.chat_id) else 'not on the allowlist')
        elif args.cmd == 'members':
            for m in BotMember.query.order_by(BotMember.id):
                print(f'{m.telegram_chat_id:>14}  {m.display_name:<24} '
                      f'web user {m.user_id or "-"}')
        elif args.cmd == 'link-user':
            if args.clear == (args.user_id is not None):
                parser.error('give a USER_ID, or --clear')
            link_user(args.chat_id, None if args.clear else args.user_id)
            print('updated')
        elif args.cmd == 'import-links':
            print(f'{import_links()} member(s) added from existing web links')
    except AdminError as exc:
        print(f'error: {exc}', file=sys.stderr)
        raise SystemExit(1)
    finally:
        Session.remove()


if __name__ == '__main__':
    main()
