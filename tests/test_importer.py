import datetime

from core.importer import import_csv, parse_datetime
from core.models import MaintenanceJob

HEADER = 'job_ref,category,description,location,maintenance_type,status,starts_at,ends_at,next_job_date\n'


def test_imports_rows_with_timeline_and_event_category(session):
    res = import_csv(HEADER +
                     'IMP-1,ACMV,Replace filters,Level 3,Preventive,In Progress,2026-11-02 09:00,2026-11-02 17:30,2026-12-02\n'
                     'IMP-2,Event,Annual fire drill,Lobby,,,05/12/2026 10:00,05/12/2026 11:00,\n')
    assert (res.created, res.updated, res.skipped) == (2, 0, [])
    j = MaintenanceJob.query.filter_by(job_ref='IMP-1').one()
    assert j.category == 'ACMV' and j.equipment_type_id and j.status == 'In Progress'
    assert j.starts_at == datetime.datetime(2026, 11, 2, 9, 0) and j.ends_at.hour == 17
    assert j.estimated_completion == datetime.date(2026, 11, 2)
    e = MaintenanceJob.query.filter_by(job_ref='IMP-2').one()
    assert e.category == 'Event' and e.starts_at == datetime.datetime(2026, 12, 5, 10, 0)


def test_reimport_updates_instead_of_duplicating(session):
    import_csv(HEADER + 'UPD-1,Lift,Inspect,B1,,,2026-11-03,,\n')
    res = import_csv(HEADER + 'UPD-1,Lift,Inspect and lubricate,B1,,,2026-11-04,,\n')
    assert (res.created, res.updated) == (0, 1)
    assert MaintenanceJob.query.filter_by(job_ref='UPD-1').count() == 1
    assert MaintenanceJob.query.filter_by(job_ref='UPD-1').one().description == 'Inspect and lubricate'


def test_bad_rows_are_skipped_with_line_and_reason_and_good_rows_still_load(session):
    res = import_csv(HEADER +
                     'BAD-1,Hovercraft,Fix,L1,,,2026-11-01,,\n'
                     'BAD-2,ACMV,Fix,L1,,,not-a-date,,\n'
                     'BAD-3,ACMV,Fix,L1,,,2026-11-05 10:00,2026-11-05 09:00,\n'
                     'GOOD-1,ACMV,Fix,L1,,,2026-11-01,,\n'
                     'BAD-4,ACMV,,L1,,,2026-11-01,,\n')
    assert res.created == 1 and [line for line, _ in res.skipped] == [2, 3, 4, 6]
    assert 'unknown equipment type' in res.skipped[0][1] and 'end is before start' in res.skipped[2][1]
    assert MaintenanceJob.query.filter_by(job_ref='GOOD-1').count() == 1
    assert MaintenanceJob.query.filter_by(job_ref='BAD-1').count() == 0


def test_missing_required_column_refuses_the_file(session):
    res = import_csv('job_ref,description\nX-1,Fix\n')
    assert res.created == 0 and 'missing required column' in res.skipped[0][1]


def test_dry_run_saves_nothing(session):
    res = import_csv(HEADER + 'DRY-1,ACMV,Fix,L1,,,2026-11-01,,\n', dry_run=True)
    assert res.created == 1 and MaintenanceJob.query.filter_by(job_ref='DRY-1').count() == 0


def test_flexible_headers_and_generated_refs(session):
    res = import_csv('Equipment Type,Job Description,Area,Start Date\nPlumbing,Flush tank,Roof,2026-11-09\n')
    assert res.created == 1
    ref = MaintenanceJob.query.filter(MaintenanceJob.description == 'Flush tank').one().job_ref
    assert ref.startswith('PLUMBING-')


def test_free_text_dates_are_kept_as_a_note(session):
    import_csv('category,description,location,estimated_completion\nACMV,Overhaul,Plant,TBC\n')
    assert MaintenanceJob.query.filter_by(description='Overhaul').one().schedule_note == 'TBC'


def test_parse_datetime_formats():
    assert parse_datetime('2026-01-05 14:30') == datetime.datetime(2026, 1, 5, 14, 30)
    assert parse_datetime('Week 3 January 2026') == datetime.datetime(2026, 1, 15)
    assert parse_datetime('') is None and parse_datetime('-') is None and parse_datetime('soon') is None
