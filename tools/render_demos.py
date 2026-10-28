"""
Render the Telegram demos in README.md from the REAL handlers and formatters.

    DATABASE_URL=postgresql://... python tools/render_demos.py --write

Everything runs inside a transaction that is rolled back, against whatever is
in the database plus a few rows this script adds for the occasion (a member, a
mapped technician, jobs dated around today). Nothing is left behind. The output
replaces the text between the demos:start/end markers in README.md, so the
demos cannot drift from the code: regenerate after changing a message.
"""

import argparse
import asyncio
import datetime
import html
import os
import re
import sys
from unittest.mock import AsyncMock, MagicMock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from sqlalchemy import text            # noqa: E402

from botapp import config, db as dbmod, notifications      # noqa: E402
from botapp.handlers import account, browse, defects        # noqa: E402
from botapp.main import button_handler                      # noqa: E402
from botapp.models import BotMember, Building, Defect, MaintenanceJob  # noqa: E402

WIDTH = 66


def plain(s):
    s = re.sub(r'</?(b|i|code|u)>', '', s)
    return html.unescape(s)


def wrap(line):
    out, cur = [], line
    while len(cur) > WIDTH:
        cut = cur.rfind(' ', 0, WIDTH)
        cut = cut if cut > 20 else WIDTH
        out.append(cur[:cut]); cur = '   ' + cur[cut:].lstrip()
    return out + [cur]


def bubble(msg, markup=None, edited=False):
    lines = []
    for raw in plain(msg).split('\n'):
        lines += wrap(raw)
    body = '\n'.join(f'  │ {l}' for l in lines)
    top = '  ┌─ bot' + (' (edited in place)' if edited else '') + ' ' + '─' * 40
    out = f'{top}\n{body}\n  └' + '─' * 52
    if markup is not None:
        for row in markup.inline_keyboard:
            out += '\n  ' + '  '.join(f'[ {b.text} ]' for b in row)
    return out


class Chat:
    """A scripted conversation that records what the bot says."""

    def __init__(self, chat_id, name='Demo'):
        self.chat_id, self.name, self.log, self.user_data = chat_id, name, [], {}

    def _update(self, text=None, data=None, photo=None):
        u = MagicMock()
        u.effective_chat.id = self.chat_id
        u.effective_user.full_name = self.name
        u.effective_user.username = 'demo'

        async def send(t, parse_mode=None, reply_markup=None):
            self.log.append(bubble(t, reply_markup))
        u.effective_chat.send_message = send
        if data is not None:
            q = MagicMock(); q.data = data; q.answer = AsyncMock()

            async def edit(t, parse_mode=None, reply_markup=None):
                self.log.append(bubble(t, reply_markup, edited=True))
            q.edit_message_text = edit
            u.callback_query = q
            u.message = None
        else:
            u.callback_query = None
            u.message.text = text
            u.message.photo = photo
            u.message.reply_text = AsyncMock(
                side_effect=lambda t, **k: self.log.append(bubble(t)))
        return u

    def _ctx(self, args=None):
        c = MagicMock(); c.args = args or []; c.user_data = self.user_data
        return c

    def say(self, line):
        self.log.append(f'you ▸ {line}')

    async def command(self, line, handler, **kw):
        self.say(line)
        parts = line.split()
        await handler(self._update(text=line), self._ctx(parts[1:]), **kw)

    async def tap(self, label, data):
        self.log.append(f'you ▸ (taps {label})')
        await button_handler(self._update(data=data), self._ctx())

    def out(self):
        return '\n'.join(self.log)


def demo(title, blurb, chat):
    return f'#### {title}\n\n{blurb}\n\n```text\n{chat.out()}\n```\n'


async def build():
    today = config.today()
    d = datetime.timedelta
    s = dbmod.Session
    web = s.execute(text("SELECT id FROM users WHERE role='technician' ORDER BY id LIMIT 1")).scalar()
    if web is None:
        raise SystemExit('seed the database first (Backend: python -m scripts.seed)')
    building = Building.query.order_by(Building.id).first()
    for ref, cat, desc, loc, status, due, nxt in [
        ('ACMV-D01', 'ACMV', 'Replace chiller filters', 'Level 3 Plant Room', 'In Progress', today, today + d(days=30)),
        ('LIFT-D01', 'Lift', 'Quarterly lift inspection', 'Block A lifts', 'Yet to Start', today + d(days=1), None),
        ('FIRE-D01', 'Fire Protection', 'Sprinkler flow test', 'Basement 1', 'Yet to Start', today + d(days=4), None),
        ('ELEC-D01', 'Electrical', 'Thermal scan of main switchboard', 'MSB room', 'Yet to Start', today - d(days=3), None),
        ('PLMB-D01', 'Plumbing', 'Flush water tanks', 'Roof tank', 'Completed', today - d(days=10), today + d(days=2)),
    ]:
        s.add(MaintenanceJob(job_ref=ref, category=cat, description=desc, location=loc,
                             maintenance_type='Preventive', status=status,
                             estimated_completion=due, next_job_date=nxt, building_id=building.id,
                             assigned_technician_id=web if ref == 'ACMV-D01' else None))
    s.flush()

    out = {}

    stranger = Chat(900001, 'Stranger')
    await stranger.command('/start', account.start_command)
    await stranger.command('/service', browse.service_command)
    out['stranger'] = demo('Someone who is not on the allowlist',
                           'They learn only their own Telegram ID, so they can ask an administrator '
                           'to add them. No data is shown.', stranger)

    s.add(BotMember(telegram_chat_id=900002, display_name='Alex Admin')); s.flush()
    a = Chat(900002, 'Alex Admin')
    await a.command('/start', account.start_command)
    out['start'] = demo('/start and /help', 'The command list, generated from the trade catalog.', a)

    a = Chat(900002, 'Alex Admin')
    await a.command('/whoami', account.whoami_command)
    out['whoami'] = demo('/whoami', 'A member with no web account link.', a)

    s.add(BotMember(telegram_chat_id=900003, display_name='Tara Tech', user_id=web)); s.flush()
    t = Chat(900003, 'Tara Tech')
    await t.command('/whoami', account.whoami_command)
    out['whoami_mapped'] = demo('/whoami (a mapped member)',
                                'This person is linked to a web-app account, so "assigned to me" works.', t)

    a = Chat(900002, 'Alex Admin')
    await a.command('/service', browse.service_command)
    out['service'] = demo('/service', 'One screen: every trade with its status counts.', a)

    a = Chat(900002, 'Alex Admin')
    await a.command('/acmv', browse.category_command, key='acmv')
    out['acmv'] = demo('/acmv  (also /lift /electrical /fire /plumbing)',
                       'Unfinished work first. Commands are generated from the catalog.', a)

    a = Chat(900002, 'Alex Admin')
    await a.tap('🛗 Lift', 'cat:lift')
    out['tap'] = demo('Tapping a button', 'Buttons edit the message in place instead of adding a new one.', a)

    a = Chat(900002, 'Alex Admin')
    await a.command('/pending', browse.pending_command)
    out['pending'] = demo('/pending', 'Every job that is not completed, across all trades.', a)

    t = Chat(900003, 'Tara Tech')
    await t.command('/myjobs', browse.my_jobs_command)
    a = Chat(900002, 'Alex Admin')
    await a.command('/myjobs', browse.my_jobs_command)
    out['myjobs'] = demo('/myjobs  (mapped member)', 'Maintenance assigned to the linked web account.', t) + \
        demo('/myjobs  (member with no web link)',
             'Nothing can be assigned to them, so the list is empty. It is never "everything".', a)

    a = Chat(900002, 'Alex Admin')
    await a.command('/defects', defects.defects_command)
    out['defects'] = demo('/defects', 'Open defects, newest first, up to 25.', a)

    t = Chat(900003, 'Tara Tech')
    await t.command('/mydefects', defects.my_defects_command)
    out['mydefects'] = demo('/mydefects', 'Defects assigned to the linked web account.', t)

    r = Chat(900002, 'Alex Admin')
    await r.command('/report', defects.report_start)
    r.say('Cracked lobby tile')
    await defects.report_title(r._update(text='Cracked lobby tile'), r._ctx())
    r.say('Tile near the lift lobby has split and is a trip hazard')
    await defects.report_description(
        r._update(text='Tile near the lift lobby has split and is a trip hazard'), r._ctx())
    r.log.append(f'you ▸ (taps "{building.name}")')
    await defects.report_building(r._update(data=f'bld:{building.id}'), r._ctx())
    r.log.append('you ▸ (taps 🔺 High)')
    await defects.report_priority(r._update(data='pri:high'), r._ctx())
    r.say('/skip')
    await defects.report_skip_photo(r._update(text='/skip'), r._ctx())
    r.say('/confirm')
    await defects.report_confirm(r._update(text='/confirm'), r._ctx())
    out['report'] = demo('/report', 'A guided conversation. Send /cancel at any step to stop.', r)

    for line, mode, title, blurb in [
        ('/calendar', None, '/calendar', 'The next 7 days, grouped by day. A line at the bottom flags overdue work.'),
        ('/today', 'today', '/today', 'Shortcut for `/calendar today`.'),
        ('/calendar month', None, '/calendar month', 'The next 30 days. Also `week` (default), `today`, `overdue`.'),
        ('/overdue', 'overdue', '/overdue', 'Unfinished jobs past their due date, oldest first.'),
    ]:
        c = Chat(900002, 'Alex Admin')
        if mode:
            await c.command(line, browse.calendar_command, mode=mode)
        else:
            await c.command(line, browse.calendar_command)
        out[line] = demo(title, blurb, c)
    c = Chat(900002, 'Alex Admin')
    await c.command('/calendar fortnight', browse.calendar_command)
    out['cal_bad'] = demo('/calendar with an unknown option', 'Anything other than today, week, month or overdue.', c)

    # An alert exactly as the poller renders it
    pending = [p for p in notifications.collect_pending() if p['chat_id'] == 900003]
    if not pending:
        dd = Defect(title='Water leak at B2 pump room', description='Steady drip from the main valve.',
                    priority='high', building_id=building.id, reporter_id=web,
                    assigned_technician_id=web)
        s.add(dd); s.flush()
        pending = [p for p in notifications.collect_pending() if p['chat_id'] == 900003]
    al = Chat(900003, 'Tara Tech')
    for p in pending[:1]:
        al.log.append(bubble(p['text']))
    out['alert'] = demo('Assignment alert (pushed by the bot)',
                        'Sent to a mapped member when a defect is assigned to their web account. '
                        'Checked every 30 s, retried on failure.', al)

    u = Chat(900002, 'Alex Admin')
    u.say('hello?')
    await account.unknown_command(u._update(text='hello?'), u._ctx())
    out['unknown'] = demo('Anything the bot does not understand', 'It points back at /start, never silence.', u)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--write', action='store_true', help='replace the demos block in README.md')
    args = ap.parse_args()

    engine = dbmod.init_engine()
    conn = engine.connect()
    outer = conn.begin()
    dbmod.Session.configure(bind=conn, join_transaction_mode='create_savepoint')
    dbmod.Session.remove()
    try:
        out = asyncio.run(build())
    finally:
        dbmod.Session.remove()
        outer.rollback()
        conn.close()

    order = ['stranger', 'start', 'whoami', 'whoami_mapped', 'service', 'acmv', 'tap', 'pending', 'myjobs',
             'defects', 'mydefects', 'report', '/calendar', '/today', '/calendar month', '/overdue',
             'cal_bad', 'alert', 'unknown']
    block = '\n'.join(out[k] for k in order)
    if args.write:
        path = os.path.join(ROOT, 'README.md')
        src = open(path).read()
        a, b = '<!-- demos:start -->', '<!-- demos:end -->'
        new = src[:src.index(a) + len(a)] + '\n\n' + block + '\n' + src[src.index(b):]
        open(path, 'w').write(new)
        print('README.md updated')
    else:
        print(block)


if __name__ == '__main__':
    main()
