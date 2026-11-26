"""
Render the Telegram demos in README.md from the REAL bot.

    DATABASE_URL=postgresql://... python tools/render_demos.py --write

It drives the production Application (the same handlers, conversations and
buttons as a live bot) with a fake Telegram, inside a transaction that is rolled
back, against demo data it adds for the occasion (scheduled items dated around
today, an earlier report, a few people). Nothing is left in the database. The
output replaces the text between the demos:start/end markers in README.md, so
the demos cannot drift from the code: regenerate after changing any message.
"""

import argparse
import datetime
import html
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import access, config, equipment, setup                                  # noqa: E402
from core import db as dbmod                                                # noqa: E402
from core.models import (BotMember, Defect, DefectComment, MaintenanceJob,  # noqa: E402
                         User)
from botapp import admin, notifications                                     # noqa: E402
from tests.harness import Chat, make_app                                     # noqa: E402

WIDTH = 64
NAMES = {5000: 'Sam (first run)', 5001: 'Alex (master control)', 5002: 'Tess (end user)', 5003: 'Sam (new person)',
         5004: 'Priya (end user)'}


def plain(s):
    return html.unescape(re.sub(r'</?(b|i|code|u)>', '', s))


def wrap(line):
    out, cur = [], line
    while len(cur) > WIDTH:
        cut = cur.rfind(' ', 0, WIDTH)
        cut = cut if cut > 20 else WIDTH
        out.append(cur[:cut])
        cur = '   ' + cur[cut:].lstrip()
    return out + [cur]


def bubble(text, markup, edited, who=None):
    lines = []
    for raw in plain(text).split('\n'):
        lines += wrap(raw)
    head = '  ┌─ bot' + (f' → {who}' if who else '') + (' (edited in place)' if edited else '') + ' '
    out = head + '─' * max(6, 56 - len(head)) + '\n' + '\n'.join(f'  │ {l}' for l in lines) + '\n  └' + '─' * 52
    if markup is not None:
        for row in markup.inline_keyboard:
            out += '\n  ' + '  '.join(f'[ {b.text} ]' for b in row)
    return out


class Scribe:
    """Runs a scripted conversation and writes it down as the user would see it."""

    def __init__(self, app, bot):
        self.app, self.bot = app, bot
        self.lines = []
        self.chats = {}

    def chat(self, chat_id):
        if chat_id not in self.chats:
            self.chats[chat_id] = Chat(self.app, self.bot, chat_id, NAMES.get(chat_id, 'Demo').split(' (')[0])
        return self.chats[chat_id]

    def _flush(self, since, acting_chat, multi):
        for chat_id, text, _m, edited, markup in self.bot.log[since:]:
            who = None
            if multi or chat_id != acting_chat:     # a message that went to someone else is labelled
                who = NAMES.get(chat_id, str(chat_id)).split(' (')[0]
            self.lines.append(bubble(text, markup, edited, who))

    def say(self, chat_id, text, multi=False):
        since = len(self.bot.log)
        shown = text.replace(*self.fixed) if getattr(self, 'fixed', None) else text
        self.lines.append(f'{NAMES.get(chat_id, chat_id).split(" (")[0]} ▸ {shown}' if multi else f'you ▸ {shown}')
        self.chat(chat_id).say(text)
        self._flush(since, chat_id, multi)

    def tap(self, chat_id, label, data, multi=False):
        since = len(self.bot.log)
        who = f'{NAMES.get(chat_id, chat_id).split(" (")[0]} ▸ ' if multi else 'you ▸ '
        self.lines.append(f'{who}(taps {label})')
        self.chat(chat_id).tap(data)
        self._flush(since, chat_id, multi)

    def note(self, text):
        self.lines.append(f'· {text}')

    def out(self):
        return '\n'.join(self.lines)


def demo(title, blurb, scribe):
    return f'#### {title}\n\n{blurb}\n\n```text\n{scribe.out()}\n```\n'


def fresh(app_bot):
    return Scribe(*app_bot)


def build():
    s = dbmod.Session
    now = config.now()
    D = datetime.timedelta

    # A clean slate for the stores the demos touch (rolled back at the end).
    DefectComment.query.delete(); MaintenanceJob.query.delete(); Defect.query.delete()
    BotMember.query.delete()
    s.flush()

    acmv, lift, elec, event = (equipment.get_by_key_or_name(k) for k in ('acmv', 'lift', 'electrical', 'event'))

    def job(ref, etype, desc, loc, start, end, status='Yet to Start'):
        j = MaintenanceJob(job_ref=ref, category=etype.name, equipment_type_id=etype.id, description=desc,
                           location=loc, maintenance_type='Preventive', status=status, starts_at=start,
                           ends_at=end, estimated_completion=end.date() if end else None)
        s.add(j); s.flush(); return j

    today9 = datetime.datetime.combine(now.date(), datetime.time(9, 0))
    job('ACMV-001', acmv, 'Replace chiller filters', 'Level 3 Plant Room', today9, today9 + D(hours=8), 'In Progress')
    job('ACMV-002', acmv, 'Cooling tower belt check', 'Roof', today9 + D(days=2), today9 + D(days=2, hours=3))
    job('LIFT-001', lift, 'Quarterly lift inspection', 'Block A lifts', today9 + D(days=1, hours=1), today9 + D(days=1, hours=3))
    job('EVT-001', event, 'Annual fire drill', 'Main lobby', today9 + D(days=3, hours=1), today9 + D(days=3, hours=2))
    job('ELEC-001', elec, 'Thermal scan of main switchboard', 'MSB room', today9 - D(days=3), today9 - D(days=3) + D(hours=2))

    # people: master control, an end user, a mapped end user with an assigned defect
    web_tech = s.execute(__import__('sqlalchemy').text(
        "INSERT INTO users (name, email, password_hash, role) VALUES ('Priya Nair','priya@demo.invalid','x',"
        "CAST('technician' AS user_roles)) RETURNING id")).scalar()
    app_bot = make_app()
    out = {}

    # --- first run: the one-time code creates the first master control -----------
    real_code = setup.create_claim('owner@example.test', 'a-long-enough-password')
    sc = fresh(app_bot)
    sc.fixed = (real_code, 'ABCDE-FGHJK')           # the code is random; show a stable one
    sc.say(5000, '/start')
    sc.say(5000, '/claim WRONG-CODE0')
    sc.say(5000, f'/claim {real_code}')
    out['first_run'] = demo('First run: claiming master control',
                            'On a fresh install nobody can approve you, so the launcher prints a one-time code '
                            '(it also asks you for an email and password for the website). The first person to send it '
                            'becomes master control. It works once, expires in 24 hours and locks after 10 wrong tries.', sc)
    BotMember.query.filter_by(telegram_chat_id=5000).delete()
    User.query.filter_by(email='owner@example.test').delete()
    s.flush()

    admin.add_member(5001, 'Alex Admin', tier='master_control')
    admin.add_member(5002, 'Tess Tan', tier='end_user')
    admin.add_member(5004, 'Priya Nair', web_user=web_tech, tier='end_user')

    from core.actor import Actor
    from core.services import report_service
    report_service.record_report(
        Actor(member_id=0, name='Mohan'), acmv.id, now - D(hours=5), 'Roof cooling tower 2',
        'Cooling tower fan is grinding loudly', specific_equipment='Cooling tower 2')

    # --- access ------------------------------------------------------------
    sc = fresh(app_bot)
    sc.say(5003, '/start')
    sc.tap(5003, 'Request access', 'acc:request')
    sc.say(5003, '/service')
    out['request'] = demo('Asking for access (once)',
                          'Someone who is not approved sees no data, only a button. After they ask, the bot remembers '
                          'the request: asking again does not notify anyone twice.', sc)

    sc = fresh(app_bot)
    mid = access.by_chat(5003).id
    sc.note('Sam has just asked for access; master control received this message:')
    for chat_id, text, _m, edited, markup in [e for e in app_bot[1].log if e[0] == 5001 and 'Access request' in e[1]][-1:]:
        sc.lines.append(bubble(text, markup, edited, 'Alex'))
    sc.tap(5001, 'Approve', f'acc:ap:{mid}', multi=True)
    sc.say(5003, '/start', multi=True)
    out['approve'] = demo('Master control approves',
                          'Approve, Approve as master, or Deny, in Telegram (or on the website). The person is told '
                          'immediately and never has to ask again.', sc)

    sc = fresh(app_bot)
    sc.say(5002, '/start')
    out['menu'] = demo('/start: the guided menu',
                       'The two guided flows lead every screen; the rest are shortcuts.', sc)
    sc = fresh(app_bot)
    sc.say(5002, '/whoami')
    sc.say(5004, '/whoami')
    sc.say(5001, '/whoami')
    out['whoami'] = demo('/whoami',
                         'Tess has no web account; Priya is linked to one (so "assigned to me" works); Alex is master control.', sc)

    # --- event query ---------------------------------------------------------
    sc = fresh(app_bot)
    sc.say(5002, '/events')
    sc.tap(5002, 'Today', 'ev:today')
    out['events_today'] = demo('Event query: a quick option', 'The bot asks when; tap a quick option.', sc)

    sc = fresh(app_bot)
    sc.tap(5002, 'Event query', 'menu:events')
    sc.tap(5002, 'Pick a date', 'ev:pick')
    sc.say(5002, 'whenever')
    d = (now + D(days=3))
    sc.say(5002, f'{d:%d %b}')
    out['events_pick'] = demo('Event query: type a date',
                              'A day or a range ("25 Nov", "25/11 - 30/11"). It says so if it cannot read it. '
                              '"Event" is an equipment type like ACMV.', sc)

    # --- defect reporting ----------------------------------------------------
    sc = fresh(app_bot)
    sc.say(5002, '/report')
    sc.tap(5002, 'Just now', 'rp:when:now')
    sc.tap(5002, 'ACMV', 'rp:type:acmv')
    sc.say(5002, 'Level 3 plant room')
    sc.say(5002, 'Chiller filters look blocked')
    sc.tap(5002, 'Yes, this one', 'rp:m:yes')
    sc.tap(5002, 'Submit', 'rp:ok')
    out['report_scheduled'] = demo('Reporting: it matches a scheduled item',
                                   'The bot asks, then looks through the scheduled and earlier unscheduled records and '
                                   'asks "Is this it?". A yes records the report against that scheduled item.', sc)

    sc = fresh(app_bot)
    sc.say(5004, '/report')
    sc.tap(5004, '3 hours ago', 'rp:when:h3')
    sc.tap(5004, 'Plumbing', 'rp:type:plumbing')
    sc.say(5004, 'Basement 2 pump room')
    sc.say(5004, 'Water dripping from the main valve')
    sc.say(5004, 'Sump pump 3')
    sc.tap(5004, 'High', 'rp:pri:high')
    sc.tap(5004, 'Skip', 'rp:skip')
    sc.tap(5004, 'Submit', 'rp:ok')
    out['report_new'] = demo('Reporting: nothing similar, so a fresh report',
                             'When neither store has a close match the bot says so and guides a new report: specific '
                             'equipment (optional), priority, optional photo, confirm.', sc)

    sc = fresh(app_bot)
    sc.say(5002, '/report')
    sc.tap(5002, 'Just now', 'rp:when:now')
    sc.tap(5002, 'ACMV', 'rp:type:acmv')
    sc.say(5002, 'cooling tower 2 on the roof')
    sc.say(5002, 'Cooling tower fan grinding again')
    sc.tap(5002, 'Yes, this one', 'rp:m:yes')
    sc.tap(5002, 'Submit', 'rp:ok')
    out['report_merge'] = demo('Reporting: it matches an earlier unscheduled report',
                               'Matches are offered most-similar first across both stores (a scheduled item wins a near tie). '
                               'Saying yes adds the new sighting to it instead of creating a duplicate. '
                               '"None of these" would create a fresh report.', sc)

    sc = fresh(app_bot)
    sc.say(5002, '/report')
    sc.tap(5002, 'Just now', 'rp:when:now')
    sc.tap(5002, 'Electrical', 'rp:type:electrical')
    sc.tap(5002, 'Back', 'rp:back')
    sc.tap(5002, 'Back', 'rp:back')
    sc.tap(5002, 'Cancel', 'rp:cancel')
    out['report_cancel'] = demo('Back and Cancel',
                                'Every step has Back and Cancel; /cancel works anywhere. Nothing is logged on cancel. '
                                'A flow left alone for 30 minutes is dropped with a message.', sc)

    # --- existing views ------------------------------------------------------
    sc = fresh(app_bot); sc.say(5002, '/service')
    out['service'] = demo('/service', 'Every equipment type on one screen. Types come from the editable list.', sc)
    sc = fresh(app_bot); sc.say(5002, '/acmv')
    out['acmv'] = demo('/acmv  (and /lift, /electrical, /fire, /plumbing, /event)',
                       'One equipment type, unfinished work first. Commands exist for the types present at start-up; '
                       'types added later are always one tap away in the menu.', sc)
    sc = fresh(app_bot); sc.tap(5002, 'Lift', 'cat:lift')
    out['tap'] = demo('Tapping a button', 'Buttons edit the message in place instead of adding a new one.', sc)
    sc = fresh(app_bot); sc.say(5002, '/pending')
    out['pending'] = demo('/pending', 'Everything not yet completed.', sc)
    sc = fresh(app_bot); sc.say(5002, '/myjobs'); sc.say(5004, '/myjobs')
    out['myjobs'] = demo('/myjobs', 'Tess has no web account, so nothing can be assigned to her (never "everything"). '
                                    'Priya is linked to one.', sc)
    sc = fresh(app_bot); sc.say(5002, '/defects')
    out['defects'] = demo('/defects', 'Open reports, newest first, up to 25. Reports added to an earlier one are not listed twice.', sc)
    sc = fresh(app_bot); sc.say(5002, '/calendar'); sc.say(5002, '/overdue')
    out['calendar'] = demo('/calendar and /overdue',
                           '`/calendar [today|week|month|overdue]` and the /today and /overdue shortcuts.', sc)
    sc = fresh(app_bot); sc.say(5001, '/access')
    out['access_cmd'] = demo('/access  (master control only)',
                             'Pending requests with buttons, and who has access. End users get "Only master control can do that".', sc)

    # assignment alert for a mapped member
    dd = Defect(title='Water leak at B2 pump room', description='Steady drip from the main valve.',
                priority='high', building_id=None, reporter_id=web_tech, assigned_technician_id=web_tech,
                kind='unscheduled', location='B2 pump room', occurred_at=now)
    s.add(dd); s.flush()
    sc = fresh(app_bot)
    pending = [p for p in notifications.collect_pending() if p['chat_id'] == 5004]
    for p in pending[:1]:
        sc.lines.append(bubble(p['text'], None, False, 'Priya'))
    out['alert'] = demo('Assignment alert (pushed by the bot)',
                        'Sent to a linked member when a defect is assigned to their web account. Checked every 30 s, retried on failure.', sc)
    return out


ORDER = ['first_run', 'request', 'approve', 'menu', 'whoami', 'events_today', 'events_pick', 'report_scheduled', 'report_new',
         'report_merge', 'report_cancel', 'service', 'acmv', 'tap', 'pending', 'myjobs', 'defects', 'calendar',
         'access_cmd', 'alert']


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
        out = build()
    finally:
        dbmod.Session.remove()
        outer.rollback()
        conn.close()

    block = '\n'.join(out[k] for k in ORDER)
    if args.write:
        path = os.path.join(ROOT, 'README.md')
        src = open(path).read()
        a, b = '<!-- demos:start -->', '<!-- demos:end -->'
        open(path, 'w').write(src[:src.index(a) + len(a)] + '\n\n' + block + '\n' + src[src.index(b):])
        print('README.md updated')
    else:
        print(block)


if __name__ == '__main__':
    main()
