import datetime

import pytest

from core import config, equipment
from core.models import Defect, DefectComment, MaintenanceJob
from botapp import admin
from tests.harness import Chat, make_app

CHAT = 7001


@pytest.fixture()
def bot_world(session, world):
    # A clean slate for the two stores the matcher searches (rolled back after the test),
    # so a developer's seeded data cannot change what is suggested.
    DefectComment.query.delete(); MaintenanceJob.query.delete(); Defect.query.delete()
    session.flush()
    app, bot = make_app()
    admin.add_member(CHAT, 'Tess')
    return Chat(app, bot, CHAT, 'Tess'), world


def acmv_id():
    return equipment.get_by_key_or_name('acmv').id


def seed_job(ref='G-1', desc='Replace chiller filters', loc='Level 3 Plant Room', hours_ahead=1, span=4):
    now = config.now()
    t = equipment.get_by_key_or_name('acmv')
    j = MaintenanceJob(job_ref=ref, category=t.name, equipment_type_id=t.id, description=desc,
                       location=loc, maintenance_type='Preventive', status='Yet to Start',
                       starts_at=now + datetime.timedelta(hours=hours_ahead - 2),
                       ends_at=now + datetime.timedelta(hours=hours_ahead + span))
    MaintenanceJob.query.session.add(j); MaintenanceJob.query.session.flush()
    return j


def start_report_to_issue(chat, location='Level 3 Plant Room'):
    chat.say('/report')
    chat.tap('rp:when:now')
    chat.tap('rp:type:acmv')
    chat.say(location)


# --- event query -------------------------------------------------------------
def test_event_query_today_shows_scheduled_items_by_type(bot_world):
    chat, _ = bot_world
    seed_job()
    assert 'When do you want to look' in chat.say('/events')[1]
    out = chat.tap('ev:today')
    assert 'Replace chiller filters' in out[1] and 'ACMV' in out[1] and 'New query' in out[2]


def test_event_query_menu_button_and_typed_date(bot_world):
    chat, _ = bot_world
    chat.tap('menu:events')
    chat.tap('ev:pick')
    assert 'could not read' in chat.say('banana')[1]
    out = chat.say('25 Dec 2099')
    assert 'Nothing is scheduled' in out[1]


def test_event_query_cancel(bot_world):
    chat, _ = bot_world
    chat.say('/events')
    assert 'Cancelled' in chat.tap('ev:cancel')[1]


# --- defect reporting --------------------------------------------------------
def test_scheduled_match_records_the_report_against_the_job(bot_world):
    chat, _ = bot_world
    j = seed_job()
    start_report_to_issue(chat)
    out = chat.say('chiller filters are blocked')
    assert 'Possible match 1 of' in out[1] and 'Scheduled item' in out[1] and j.job_ref in out[1]
    assert 'Yes, this one' in out[2] and 'None of these' in out[2]
    confirm = chat.tap('rp:m:yes')
    assert 'Ready to submit' in confirm[1] and j.job_ref in confirm[1]
    done = chat.tap('rp:ok')
    assert 'Recorded against scheduled item G-1' in done[1]
    d = Defect.query.filter_by(maintenance_job_id=j.id).one()
    assert d.kind == 'scheduled' and d.equipment_type_id == acmv_id() and d.bot_reporter_id is not None


def test_unscheduled_match_adds_to_the_earlier_report(bot_world):
    chat, _ = bot_world
    first = Chat(chat.app, chat.bot, CHAT, 'Tess')
    start_report_to_issue(first, 'Roof cooling tower')
    first.say('Cooling tower fan is grinding loudly')       # nothing similar yet
    assert 'nothing similar' in first.mine()[-2][1]
    first.tap('rp:skip'); first.tap('rp:pri:high'); first.tap('rp:skip')
    first.tap('rp:ok')
    original = Defect.query.filter_by(kind='unscheduled').order_by(Defect.id.desc()).first()
    start_report_to_issue(chat, 'roof cooling tower')
    out = chat.say('cooling tower fan grinding noise again')
    assert 'Earlier unscheduled report' in out[1] and f'#{original.id}' in out[1]
    chat.tap('rp:m:yes')
    done = chat.tap('rp:ok')
    assert f'Added to the earlier report #{original.id}' in done[1]
    assert Defect.query.filter(Defect.merged_into_id == original.id).count() == 1


def test_no_match_leads_to_a_fresh_report_with_specific_equipment_and_priority(bot_world):
    chat, _ = bot_world
    start_report_to_issue(chat, 'Basement 2 pump room')
    out = chat.say('Water dripping from the main valve')
    assert 'nothing similar' in chat.mine()[-2][1] and 'specific equipment' in out[1]
    chat.say('Sump pump 3')
    chat.tap('rp:pri:high')
    summary = chat.tap('rp:skip')                      # skip the photo
    assert 'new unscheduled report' in summary[1] and 'Sump pump 3' in summary[1]
    done = chat.tap('rp:ok')
    assert 'New report created' in done[1]
    d = Defect.query.order_by(Defect.id.desc()).first()
    assert d.kind == 'unscheduled' and d.priority == 'high' and d.specific_equipment == 'Sump pump 3'
    assert d.occurred_at is not None and d.location == 'Basement 2 pump room'


def test_none_of_these_creates_a_fresh_report_even_when_matches_exist(bot_world):
    chat, _ = bot_world
    seed_job()
    start_report_to_issue(chat)
    chat.say('chiller filters are blocked')
    out = chat.tap('rp:m:none')
    assert 'specific equipment' in out[1]
    chat.tap('rp:skip'); chat.tap('rp:pri:low'); chat.tap('rp:skip')
    chat.tap('rp:ok')
    assert Defect.query.order_by(Defect.id.desc()).first().kind == 'unscheduled'


def test_next_match_steps_through_the_candidates(bot_world):
    chat, _ = bot_world
    seed_job('G-A', 'Replace chiller filters', 'Level 3 Plant Room')
    seed_job('G-B', 'Chiller filters inspection', 'Level 3 Plant Room')
    start_report_to_issue(chat)
    first = chat.say('chiller filters blocked')
    assert 'match 1 of 2' in first[1] and 'Next match' in first[2]
    second = chat.tap('rp:m:next')
    assert 'match 2 of 2' in second[1] and 'Next match' not in second[2]


def test_unreadable_when_is_asked_again_and_typed_time_is_accepted(bot_world):
    chat, _ = bot_world
    chat.say('/report')
    assert 'could not read' in chat.say('whenever')[1]
    assert 'equipment type' in chat.say('14:30')[1].lower()


def test_future_time_is_refused(bot_world):
    chat, _ = bot_world
    chat.say('/report')
    assert 'future' in chat.say('25 Dec 2099')[1]


def test_back_steps_return_to_the_previous_prompt(bot_world):
    chat, _ = bot_world
    chat.say('/report'); chat.tap('rp:when:now'); chat.tap('rp:type:acmv')
    assert 'Where is it' in chat.last_text()
    assert 'Which equipment type' in chat.tap('rp:back')[1]
    assert 'When did it happen' in chat.tap('rp:back')[1]


def test_cancel_stops_and_logs_nothing(bot_world):
    chat, _ = bot_world
    before = Defect.query.count()
    start_report_to_issue(chat)
    assert 'Cancelled' in chat.tap('rp:cancel')[1]
    assert Defect.query.count() == before
    assert 'Cancelled' in (chat.say('/report') and chat.say('/cancel'))[1]


def test_short_answers_are_re_prompted(bot_world):
    chat, _ = bot_world
    chat.say('/report'); chat.tap('rp:when:now'); chat.tap('rp:type:acmv')
    assert 'tell me where' in chat.say('x')[1]
    chat.say('Level 3')
    assert 'detail' in chat.say('bad')[1]


def test_a_stranger_cannot_start_a_report_or_an_event_query(bot_world):
    chat, _ = bot_world
    stranger = Chat(chat.app, chat.bot, 7999, 'Nobody')
    for cmd in ('/report', '/events'):
        out = stranger.say(cmd)
        assert 'do not have access' in out[1] and 'Request access' in out[2]
    assert Defect.query.filter(Defect.reporter_label == 'Nobody').count() == 0


def test_the_menu_offers_both_guided_flows(bot_world):
    chat, _ = bot_world
    out = chat.say('/start')
    assert 'Event query' in out[2] and 'Report a defect' in out[2]
    assert 'Signed in as' in out[1]
