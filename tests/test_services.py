import pytest

from core.actor import Actor
from core.models import Defect, DefectComment, MaintenanceJob
from core.services import defect_service as ds
from core.services import maintenance_service as ms


def actor(member_id=1, user_id=None, name='Pat'):
    return Actor(member_id=member_id, name=name, user_id=user_id)


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
    from core.fm import formatters
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
    from core.fm import formatters
    for i in range(65):
        _job(f'CAP-{i:03d}', due=TODAY)
    text = formatters.calendar_message('x', ms.calendar_entries(TODAY, TODAY), TODAY, empty='-')
    assert 'more' in text and text.count('<code>CAP-') == formatters.CALENDAR_MAX_ENTRIES


def test_empty_calendar_says_so(session, world):
    from core.fm import formatters
    far = datetime.date(2099, 1, 1)
    assert 'Nothing scheduled' in formatters.calendar_message(
        'x', ms.calendar_entries(far, far), far, empty='Nothing scheduled in this period.')


def test_today_uses_the_configured_timezone(monkeypatch):
    from core import config
    monkeypatch.setenv('TZ', 'Pacific/Kiritimati')   # UTC+14
    ahead = config.today()
    monkeypatch.setenv('TZ', 'Pacific/Pago_Pago')    # UTC-11
    behind = config.today()
    assert (ahead - behind).days in (0, 1)
    monkeypatch.setenv('TZ', 'Not/AZone')
    assert isinstance(config.today(), datetime.date)  # falls back, never raises


# --- event query -------------------------------------------------------------
def test_events_between_uses_the_timeline_and_falls_back_to_dates(session, world):
    from core import equipment
    t = equipment.get_by_key_or_name('acmv')
    D = datetime.datetime
    def mk(ref, **kw):
        j = MaintenanceJob(job_ref=ref, category='ACMV', equipment_type_id=t.id, description=ref,
                           location='L', maintenance_type='Preventive', status='Yet to Start', **kw)
        session.add(j); session.flush(); return j
    mk('EV-INSIDE', starts_at=D(2026, 12, 2, 9), ends_at=D(2026, 12, 2, 17))
    mk('EV-SPANS', starts_at=D(2026, 12, 1), ends_at=D(2026, 12, 5))
    mk('EV-BEFORE', starts_at=D(2026, 11, 20), ends_at=D(2026, 11, 21))
    mk('EV-AFTER', starts_at=D(2026, 12, 20), ends_at=D(2026, 12, 21))
    mk('EV-DATEONLY', next_job_date=datetime.date(2026, 12, 3))
    mk('EV-NODATE')
    refs = [j.job_ref for j in ms.events_between(D(2026, 12, 2), D(2026, 12, 3, 23, 59, 59))]
    assert set(refs) >= {'EV-INSIDE', 'EV-SPANS', 'EV-DATEONLY'}
    assert not set(refs) & {'EV-BEFORE', 'EV-AFTER', 'EV-NODATE'}
    only_acmv = ms.events_between(D(2026, 12, 2), D(2026, 12, 3), equipment_type_id=t.id)
    assert all(j.equipment_type_id == t.id for j in only_acmv)
