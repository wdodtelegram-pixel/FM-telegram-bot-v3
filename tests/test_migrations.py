"""
The migration chain, run for real on throwaway databases.

Needs a role that may CREATE DATABASE (the usual local postgres role).
"""
import os
import subprocess
import sys
import uuid

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from tests.conftest import URL

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _admin_engine():
    return create_engine(make_url(URL).set(database='postgres'), isolation_level='AUTOCOMMIT')


@pytest.fixture()
def scratch_db():
    name = 'fm_mig_' + uuid.uuid4().hex[:8]
    admin = _admin_engine()
    try:
        with admin.connect() as c:
            c.execute(text(f'CREATE DATABASE {name}'))
    except Exception as exc:
        pytest.skip(f'cannot create a scratch database: {exc}')
    url = make_url(URL).set(database=name).render_as_string(hide_password=False)
    yield url
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS {name} WITH (FORCE)'))


def alembic(url, *args):
    env = dict(os.environ, DATABASE_URL=url)
    return subprocess.run([sys.executable, '-m', 'alembic', '-c', 'migrations/alembic.ini', *args],
                          cwd=ROOT, env=env, capture_output=True, text=True)


def test_an_empty_database_gets_the_whole_schema_and_the_seeded_types(scratch_db):
    r = alembic(scratch_db, 'upgrade', 'head')
    assert r.returncode == 0, r.stderr
    eng = create_engine(scratch_db)
    tables = set(inspect(eng).get_table_names())
    assert {'users', 'buildings', 'defects', 'defect_comments', 'maintenance_jobs', 'equipment_types',
            'bot_members', 'bot_notification_log'} <= tables
    with eng.connect() as c:
        keys = [r[0] for r in c.execute(text('SELECT key FROM equipment_types ORDER BY sort_order'))]
    assert keys == ['acmv', 'lift', 'electrical', 'fire', 'plumbing', 'event']
    cols = {c['name'] for c in inspect(eng).get_columns('defects')}
    assert {'kind', 'occurred_at', 'location', 'specific_equipment', 'maintenance_job_id', 'merged_into_id',
            'bot_reporter_id', 'reporter_label'} <= cols
    assert inspect(eng).get_columns('defects')[[c['name'] for c in inspect(eng).get_columns('defects')]
                                                 .index('building_id')]['nullable']


def test_upgrade_is_repeatable_and_downgrade_then_upgrade_round_trips(scratch_db):
    assert alembic(scratch_db, 'upgrade', 'head').returncode == 0
    assert alembic(scratch_db, 'upgrade', 'head').returncode == 0
    down = alembic(scratch_db, 'downgrade', '0004')
    assert down.returncode == 0, down.stderr
    up = alembic(scratch_db, 'upgrade', 'head')
    assert up.returncode == 0, up.stderr


def test_an_existing_web_app_database_is_upgraded_in_place_and_keeps_its_rows(scratch_db):
    # Reach the state of a database made by the old web app + the first bot release: baseline then 0004.
    assert alembic(scratch_db, 'upgrade', '0004').returncode == 0
    eng = create_engine(scratch_db)
    with eng.begin() as c:
        c.execute(text("INSERT INTO users (name, email, password_hash, role) "
                       "VALUES ('Old User', 'old@example.test', 'x', 'admin')"))
        uid = c.execute(text("SELECT id FROM users")).scalar()
        c.execute(text("INSERT INTO buildings (name, address) VALUES ('Tower A', '1 Rd')"))
        bid = c.execute(text("SELECT id FROM buildings")).scalar()
        c.execute(text("INSERT INTO defects (title, description, priority, building_id, reporter_id, created_at) "
                       "VALUES ('Old defect', 'from before', 'low', :b, :u, now())"), {'b': bid, 'u': uid})
        c.execute(text("INSERT INTO maintenance_jobs (job_ref, category, description, location, "
                       "estimated_completion, next_job_date) VALUES ('OLD-1', 'ACMV', 'Old job', 'L1', "
                       "'2026-12-01', '2026-12-15')"))
        c.execute(text("INSERT INTO bot_members (telegram_chat_id, display_name, joined_at) "
                       "VALUES (4242, 'Old Member', now())"))
    r = alembic(scratch_db, 'upgrade', 'head')
    assert r.returncode == 0, r.stderr
    with eng.connect() as c:
        d = c.execute(text("SELECT kind, occurred_at IS NOT NULL FROM defects")).one()
        j = c.execute(text("SELECT equipment_type_id IS NOT NULL, starts_at, ends_at FROM maintenance_jobs")).one()
        m = c.execute(text("SELECT tier, status, notified_status FROM bot_members")).one()
    assert tuple(d) == ('unscheduled', True)                        # old defects are backfilled
    assert j[0] and str(j[1]).startswith('2026-12-15') and str(j[2]).startswith('2026-12-01')
    assert tuple(m) == ('master_control', 'approved', 'approved')   # existing members stay approved, not re-announced
