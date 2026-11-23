import datetime

import pytest

from core import equipment, similarity
from core.actor import Actor
from core.models import Defect, DefectComment, MaintenanceJob
from core.services import report_service as rs

NOW = datetime.datetime(2026, 11, 10, 10, 0)


@pytest.fixture()
def acmv(session):
    return equipment.get_by_key_or_name('acmv')


def actor(member_id=1, user_id=None):
    return Actor(member_id=member_id, name='Pat', user_id=user_id, tier='end_user')


def job(acmv, ref, desc, loc, start, end, status='Yet to Start'):
    j = MaintenanceJob(job_ref=ref, category=acmv.name, equipment_type_id=acmv.id, description=desc,
                       location=loc, maintenance_type='Preventive', status=status,
                       starts_at=start, ends_at=end)
    MaintenanceJob.query.session.add(j)
    MaintenanceJob.query.session.flush()
    return j


def test_exact_scheduled_match_scores_high_and_explains_itself(session, acmv):
    job(acmv, 'SIM-1', 'Replace chiller filters', 'Level 3 Plant Room',
        NOW - datetime.timedelta(hours=1), NOW + datetime.timedelta(hours=6))
    m = similarity.find_matches(acmv.id, NOW, 'level 3 plant room', 'chiller filters dirty')
    top = m['scheduled'][0]
    assert top.score >= 70 and 'falls within its scheduled time' in top.reasons
    assert 'similar location' in top.reasons and m['unscheduled'] == []


def test_wrong_equipment_type_never_matches(session, acmv):
    lift = equipment.get_by_key_or_name('lift')
    job(acmv, 'SIM-2', 'Replace chiller filters', 'Level 3 Plant Room', NOW, NOW)
    assert similarity.find_matches(lift.id, NOW, 'Level 3 Plant Room', 'chiller filters') == \
        {'scheduled': [], 'unscheduled': []}


def test_far_in_time_and_unrelated_text_is_not_suggested(session, acmv):
    job(acmv, 'SIM-3', 'Replace chiller filters', 'Level 3 Plant Room',
        NOW + datetime.timedelta(days=60), NOW + datetime.timedelta(days=60))
    m = similarity.find_matches(acmv.id, NOW, 'Car park B2', 'water dripping from ceiling')
    assert m == {'scheduled': [], 'unscheduled': []}


def test_unscheduled_match_finds_an_earlier_open_report(session, acmv, world):
    first = rs.record_report(actor(), acmv.id, NOW - datetime.timedelta(hours=3),
                             'Level 3 Plant Room', 'Chiller making a loud grinding noise')
    m = rs.suggest(acmv.id, NOW, 'plant room level 3', 'grinding noise from the chiller')
    assert [x.record_id for x in m['unscheduled']] == [first['defect_id']] and not m['scheduled']


def test_completed_and_merged_reports_are_not_suggested(session, acmv):
    a = rs.record_report(actor(), acmv.id, NOW, 'Level 3 Plant Room', 'Chiller grinding noise')
    Defect.query.get(a['defect_id']).status = 'Completed'
    session.flush()
    assert rs.suggest(acmv.id, NOW, 'Level 3 Plant Room', 'Chiller grinding noise')['unscheduled'] == []


def test_choice_scheduled_links_the_defect_and_is_kind_scheduled(session, acmv):
    j = job(acmv, 'SIM-4', 'Replace chiller filters', 'Level 3 Plant Room', NOW, NOW)
    res = rs.record_report(actor(), acmv.id, NOW, 'Level 3 Plant Room', 'Filters are blocked',
                           choice=('scheduled', j.id))
    d = Defect.query.get(res['defect_id'])
    assert res['outcome'] == 'linked_scheduled' and d.kind == 'scheduled' and d.maintenance_job_id == j.id
    assert d.occurred_at == NOW and d.reporter_id is None and d.bot_reporter_id == 1


def test_choice_unscheduled_adds_to_the_existing_report_without_a_duplicate_listing(session, acmv, world):
    from core.services import defect_service as ds
    first = rs.record_report(actor(), acmv.id, NOW, 'Level 3 Plant Room', 'Chiller grinding noise')
    res = rs.record_report(actor(2), acmv.id, NOW + datetime.timedelta(hours=1), 'Plant room L3',
                           'Still grinding, getting worse', choice=('unscheduled', first['defect_id']))
    assert res['outcome'] == 'merged' and res['parent_id'] == first['defect_id']
    parent_comments = DefectComment.query.filter_by(defect_id=first['defect_id']).all()
    assert any('Additional report' in (c.initial_report or '') for c in parent_comments)
    listed = [d.id for d in ds.list_visible_defects(actor(), limit=500)]
    assert first['defect_id'] in listed and res['defect_id'] not in listed


def test_choice_new_creates_a_fresh_unscheduled_report(session, acmv):
    res = rs.record_report(actor(), acmv.id, NOW, 'Roof', 'Pigeons nesting in the cooling tower',
                           specific_equipment='Cooling tower 2', priority='high')
    d = Defect.query.get(res['defect_id'])
    assert res['outcome'] == 'created' and d.kind == 'unscheduled' and d.priority == 'high'
    assert d.specific_equipment == 'Cooling tower 2' and d.maintenance_job_id is None and d.merged_into_id is None


def test_known_building_in_the_location_is_linked(session, acmv, world):
    res = rs.record_report(actor(), acmv.id, NOW, 'Tower A, roof plant', 'Fan belt squealing loudly')
    assert Defect.query.get(res['defect_id']).building_id == world['building'].id


@pytest.mark.parametrize('kw,msg', [
    (dict(location=''), 'where'),
    (dict(issue='hi'), 'describe'),
    (dict(when=None), 'date'),
    (dict(when=datetime.datetime(2099, 1, 1)), 'future'),
    (dict(priority='urgent'), 'Priority'),
])
def test_validation(session, acmv, kw, msg):
    args = dict(when=NOW, location='Roof', issue='Fan is broken badly', priority='low')
    args.update(kw)
    with pytest.raises(rs.ReportError, match=msg):
        rs.record_report(actor(), acmv.id, args.pop('when'), args.pop('location'), args.pop('issue'), **args)


def test_a_choice_must_match_the_chosen_type_and_still_exist(session, acmv):
    lift = equipment.get_by_key_or_name('lift')
    j = job(acmv, 'SIM-5', 'x', 'y', NOW, NOW)
    with pytest.raises(rs.ReportError):
        rs.record_report(actor(), lift.id, NOW, 'Roof', 'Escalator stuck again', choice=('scheduled', j.id))
    with pytest.raises(rs.ReportError):
        rs.record_report(actor(), acmv.id, NOW, 'Roof', 'Fan is broken badly', choice=('unscheduled', 999999))


def test_text_similarity_basics():
    assert similarity.text_similarity('', 'anything') == 0
    assert similarity.text_similarity('chiller filters', 'Chiller filter replacement') > 0.5
    assert similarity.text_similarity('water leak', 'lift stuck') < 0.3
