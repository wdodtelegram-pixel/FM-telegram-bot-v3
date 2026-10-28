import pytest

from botapp.actor import Actor
from botapp.models import Defect, DefectComment, MaintenanceJob
from botapp.services import defect_service as ds
from botapp.services import maintenance_service as ms


def actor(member_id=1, user_id=None, name='Pat'):
    return Actor(member_id=member_id, name=name, user_id=user_id)


def test_bot_only_csr_can_report_and_is_recorded_as_a_bot_reporter(session, world):
    d = ds.create_defect(actor(member_id=7), 'Cracked tile', 'Lobby floor', world['building'].id, 'high')
    row = Defect.query.get(d.id)
    assert row.reporter_id is None and row.bot_reporter_id == 7 and row.reporter_label == 'Pat'
    assert DefectComment.query.filter_by(defect_id=d.id).count() == 1


def test_mapped_member_is_attributed_to_their_web_account(session, world):
    d = ds.create_defect(actor(user_id=world['csr'].id), 'Leak', 'Roof leak', world['building'].id, 'low')
    row = Defect.query.get(d.id)
    assert row.reporter_id == world['csr'].id and row.bot_reporter_id is None


@pytest.mark.parametrize('kw', [dict(title=' ', description='ok desc'),
                                dict(title='ok', description=''),
                                dict(title='ok', description='ok desc', priority='urgent'),
                                dict(title='ok', description='ok desc', building_id=999999)])
def test_validation(session, world, kw):
    args = dict(title='t', description='d' * 6, building_id=world['building'].id, priority='low')
    args.update(kw)
    with pytest.raises(ds.DefectError):
        ds.create_defect(actor(), **args)


def _defect(world, **kw):
    d = Defect(title='t', description='d', priority='low', building_id=world['building'].id,
               reporter_id=world['csr'].id, **kw)
    Defect.query.session.add(d)
    Defect.query.session.flush()
    return d


def test_mydefects_is_the_mapped_accounts_assignments_and_empty_without_one(session, world):
    mine = _defect(world, assigned_technician_id=world['tech'].id)
    _defect(world)                                      # unassigned
    seen = ds.list_visible_defects(actor(user_id=world['tech'].id), assigned_only=True)
    assert [d.id for d in seen] == [mine.id]
    # The IS NULL trap: no mapped account must NOT mean "all unassigned defects".
    assert ds.list_visible_defects(actor(user_id=None), assigned_only=True) == []


def test_everyone_sees_every_open_defect(session, world):
    a = _defect(world, assigned_technician_id=world['tech'].id); b = _defect(world)
    ids = {d.id for d in ds.list_visible_defects(actor())}
    assert {a.id, b.id} <= ids


def test_completed_and_completed_or_deleted(session, world):
    a = _defect(world); b = _defect(world, status='Completed'); c = _defect(world)
    import datetime; c.deleted_at = datetime.datetime.utcnow(); session.flush()
    ids = {d.id for d in ds.list_visible_defects(actor())}
    assert a.id in ids and b.id not in ids and c.id not in ids


def test_list_cap_is_25(session, world):
    for _ in range(30):
        _defect(world)
    assert len(ds.list_visible_defects(actor())) == 25


def test_maintenance_reads_and_unknown_category(session, world):
    session.add(MaintenanceJob(job_ref='ACMV-T1', category='ACMV', description='Filter', location='L3',
                               maintenance_type='Preventive', status='In Progress',
                               assigned_technician_id=world['tech'].id))
    session.flush()
    assert any(j.job_ref == 'ACMV-T1' for j in ms.list_jobs(outstanding=True))
    assert [j.job_ref for j in ms.list_jobs(technician_id=world['tech'].id)] == ['ACMV-T1']
    assert ms.summary_counts()['acmv']['In Progress'] >= 1
    with pytest.raises(ms.MaintenanceError):
        ms.jobs_for_category('nonsense')


def test_myjobs_for_member_without_web_account_is_empty_not_everything(session, world):
    from botapp.handlers import browse
    session.add(MaintenanceJob(job_ref='LIFT-T1', category='Lift', description='Cable', location='B1',
                               maintenance_type='Preventive', status='Yet to Start'))
    session.flush()
    assert 'LIFT-T1' not in browse._render_my_jobs(None)


# --- calendar ---------------------------------------------------------------
import datetime

TODAY = datetime.date(2026, 10, 28)


def _job(ref, status='Yet to Start', due=None, nxt=None, **kw):
    j = MaintenanceJob(job_ref=ref, category='ACMV', description=f'Job {ref}', location='L1',
                       maintenance_type='Preventive', status=status,
                       estimated_completion=due, next_job_date=nxt, **kw)
    Defect.query.session.add(j)
    Defect.query.session.flush()
    return j


def test_calendar_window_is_inclusive_and_excludes_outside(session, world):
    _job('CAL-IN-START', due=TODAY)
    _job('CAL-IN-END', due=TODAY + datetime.timedelta(days=6))
    _job('CAL-OUT-LATE', due=TODAY + datetime.timedelta(days=7))
    _job('CAL-OUT-EARLY', due=TODAY - datetime.timedelta(days=1))
    refs = {j.job_ref for _, _, j in ms.calendar_entries(TODAY, TODAY + datetime.timedelta(days=6))}
    assert {'CAL-IN-START', 'CAL-IN-END'} <= refs
    assert not refs & {'CAL-OUT-LATE', 'CAL-OUT-EARLY'}


def test_completed_job_shows_next_service_but_not_due(session, world):
    _job('CAL-DONE', status='Completed', due=TODAY, nxt=TODAY + datetime.timedelta(days=3))
    kinds = [(k, j.job_ref) for _, k, j in
             ms.calendar_entries(TODAY, TODAY + datetime.timedelta(days=6)) if j.job_ref == 'CAL-DONE']
    assert kinds == [('next', 'CAL-DONE')]


def test_overdue_excludes_completed_and_undated(session, world):
    _job('OD-LATE', due=TODAY - datetime.timedelta(days=3))
    _job('OD-DONE', status='Completed', due=TODAY - datetime.timedelta(days=3))
    _job('OD-NODATE')
    refs = [j.job_ref for _, _, j in ms.overdue_entries(TODAY)]
    assert 'OD-LATE' in refs and 'OD-DONE' not in refs and 'OD-NODATE' not in refs


def test_calendar_message_groups_by_day_and_flags_overdue(session, world):
    from botapp.fm import formatters
    _job('MSG-1', due=TODAY)
    _job('MSG-2', due=TODAY + datetime.timedelta(days=1))
    _job('MSG-OD', due=TODAY - datetime.timedelta(days=2))
    text = formatters.calendar_message(
        'Next 7 days', ms.calendar_entries(TODAY, TODAY + datetime.timedelta(days=6)), TODAY,
        empty='-', overdue_count=len(ms.overdue_entries(TODAY)))
    assert '(today)' in text and '(tomorrow)' in text and 'overdue' in text
    od = formatters.calendar_message('Overdue', ms.overdue_entries(TODAY), TODAY, empty='-',
                                     show_overdue_hint=False)
    assert '2 days overdue' in od


def test_calendar_caps_long_lists(session, world):
    from botapp.fm import formatters
    for i in range(65):
        _job(f'CAP-{i:03d}', due=TODAY)
    text = formatters.calendar_message('x', ms.calendar_entries(TODAY, TODAY), TODAY, empty='-')
    assert 'more' in text and text.count('<code>CAP-') == formatters.CALENDAR_MAX_ENTRIES


def test_empty_calendar_says_so(session, world):
    from botapp.fm import formatters
    far = datetime.date(2099, 1, 1)
    assert 'Nothing scheduled' in formatters.calendar_message(
        'x', ms.calendar_entries(far, far), far, empty='Nothing scheduled in this period.')


def test_today_uses_the_configured_timezone(monkeypatch):
    from botapp import config
    monkeypatch.setenv('TZ', 'Pacific/Kiritimati')   # UTC+14
    ahead = config.today()
    monkeypatch.setenv('TZ', 'Pacific/Pago_Pago')    # UTC-11
    behind = config.today()
    assert (ahead - behind).days in (0, 1)
    monkeypatch.setenv('TZ', 'Not/AZone')
    assert isinstance(config.today(), datetime.date)  # falls back, never raises
