import datetime
import io
import types

import pytest

from botapp import admin
from core import access, config, equipment
from core.models import BotMember, Defect, MaintenanceJob
from core.services import report_service as rs
from core.actor import Actor

PASSWORD = 'correct-horse-battery'


@pytest.fixture()
def client(session, world, monkeypatch):
    monkeypatch.setenv('SECRET_KEY', 'test-secret')
    from api.app import create_app
    app = create_app(init_db=False)
    return app.test_client()


@pytest.fixture()
def master(session):
    admin.add_member(9001, 'Boss', tier='master_control')
    admin.create_web_login(9001, 'boss@example.test', PASSWORD)
    # a plain value: each API request closes the session, so a model instance would detach
    return types.SimpleNamespace(id=access.by_chat(9001).id)


def login(client, email='boss@example.test', password=PASSWORD):
    return client.post('/api/auth/login', json={'email': email, 'password': password})


def auth(client, **kw):
    token = login(client, **kw).get_json()['token']
    return {'Authorization': f'Bearer {token}'}


# --- sign-in -----------------------------------------------------------------
def test_master_control_can_sign_in_and_see_who_they_are(client, master):
    r = login(client)
    assert r.status_code == 200 and r.get_json()['user']['tier'] == 'master_control'
    me = client.get('/api/auth/me', headers=auth(client)).get_json()
    assert me['name'] == 'Boss'


def test_wrong_password_and_unknown_email_get_the_same_answer(client, master):
    a = login(client, password='nope-nope-nope')
    b = login(client, email='ghost@example.test')
    assert a.status_code == b.status_code == 401 and a.get_json() == b.get_json()


def test_an_end_user_cannot_sign_in_to_the_website(client, session):
    admin.add_member(9002, 'Plain', tier='end_user')
    # give them a users row anyway: the tier, not the password, decides
    from core.models import User
    from core.passwords import hash_password
    u = User(name='Plain', email='plain@example.test', role='csr', password_hash=hash_password(PASSWORD))
    session.add(u); session.flush()
    access.by_chat(9002).user_id = u.id
    session.flush()
    r = login(client, email='plain@example.test')
    assert r.status_code == 403 and 'website access' in r.get_json()['error']


def test_every_endpoint_needs_a_token(client, master):
    for path in ('/api/dashboard', '/api/scheduled', '/api/defects', '/api/access/members',
                 '/api/equipment-types', '/api/auth/me'):
        assert client.get(path).status_code == 401, path
    assert client.get('/api/dashboard', headers={'Authorization': 'Bearer junk'}).status_code == 401


def test_revoking_a_master_cuts_off_their_existing_token_immediately(client, master, session):
    admin.add_member(9003, 'Second', tier='master_control')
    admin.create_web_login(9003, 'second@example.test', PASSWORD)
    headers = auth(client, email='second@example.test')
    assert client.get('/api/dashboard', headers=headers).status_code == 200
    access.revoke(access.by_chat(9003).id, by_member_id=master.id)
    assert client.get('/api/dashboard', headers=headers).status_code == 403


def test_expired_token_is_refused(client, master, monkeypatch):
    client.application.config['JWT_HOURS'] = -1
    r = client.get('/api/dashboard', headers=auth(client))
    assert r.status_code == 401 and 'expired' in r.get_json()['error']


def test_health_is_open(client):
    assert client.get('/api/health').get_json() == {'status': 'ok'}


# --- stores ------------------------------------------------------------------
def seed_store(session):
    # a clean slate for the stores (rolled back after the test) so seeded demo data cannot interfere
    from core.models import DefectComment
    DefectComment.query.delete(); MaintenanceJob.query.delete(); Defect.query.delete()
    session.flush()
    t = equipment.get_by_key_or_name('acmv')
    now = config.now()
    session.add_all([
        MaintenanceJob(job_ref='API-1', category=t.name, equipment_type_id=t.id, description='Replace filters',
                       location='Level 3', maintenance_type='Preventive', status='In Progress',
                       starts_at=now - datetime.timedelta(hours=1), ends_at=now + datetime.timedelta(hours=3),
                       estimated_completion=now.date() - datetime.timedelta(days=2)),
        MaintenanceJob(job_ref='API-2', category=t.name, equipment_type_id=t.id, description='Other work',
                       location='Roof', maintenance_type='Preventive', status='Completed',
                       starts_at=now + datetime.timedelta(days=30), ends_at=now + datetime.timedelta(days=30))])
    session.flush()
    actor = Actor(member_id=1, name='Pat', user_id=None)
    res = rs.record_report(actor, t.id, now, 'Level 3 Plant Room', 'Chiller grinding noise')
    return res


def test_dashboard_counts_all_three_stores(client, master, session):
    seed_store(session)
    d = client.get('/api/dashboard', headers=auth(client)).get_json()
    assert d['scheduled']['total'] >= 2 and d['scheduled']['today'] >= 1 and d['scheduled']['overdue'] >= 1
    assert d['reports']['unscheduled'] >= 1 and d['access']['master_control'] >= 1
    assert any(t['key'] == 'event' for t in d['scheduled']['by_type'])


def test_scheduled_filters_search_and_paging(client, master, session):
    seed_store(session)
    h = auth(client)
    r = client.get('/api/scheduled?type=acmv&q=filters', headers=h).get_json()
    assert [i['job_ref'] for i in r['items']] == ['API-1'] and r['total'] == 1
    assert client.get('/api/scheduled?status=Completed&type=acmv', headers=h).get_json()['items'][0]['job_ref'] == 'API-2'
    assert client.get('/api/scheduled?type=nope', headers=h).status_code == 400
    day = config.now().date().isoformat()
    assert 'API-1' in [i['job_ref'] for i in client.get(f'/api/scheduled?from={day}&to={day}', headers=h).get_json()['items']]
    paged = client.get('/api/scheduled?per_page=1&page=2', headers=h).get_json()
    assert len(paged['items']) == 1 and paged['pages'] >= 2


def test_import_csv_dry_run_then_real(client, master, session):
    csv = 'job_ref,category,description,location,starts_at\nWEB-1,Event,Fire drill,Lobby,2026-12-05 10:00\nWEB-2,Nope,x,y,\n'
    h = auth(client)
    dry = client.post('/api/scheduled/import', headers=h, data={'dry_run': '1', 'file': (io.BytesIO(csv.encode()), 'a.csv')},
                      content_type='multipart/form-data').get_json()
    assert dry['created'] == 1 and dry['skipped'][0]['line'] == 3 and dry['dry_run']
    assert MaintenanceJob.query.filter_by(job_ref='WEB-1').count() == 0
    real = client.post('/api/scheduled/import', headers=h, data={'file': (io.BytesIO(csv.encode()), 'a.csv')},
                       content_type='multipart/form-data').get_json()
    assert real['created'] == 1 and MaintenanceJob.query.filter_by(job_ref='WEB-1').count() == 1
    assert client.post('/api/scheduled/import', headers=h).status_code == 400


def test_defects_list_detail_and_merged_reports(client, master, session):
    first = seed_store(session)
    t = equipment.get_by_key_or_name('acmv')
    rs.record_report(Actor(member_id=2, name='Sam', user_id=None), t.id, config.now(), 'plant room level 3',
                     'Chiller still grinding', choice=('unscheduled', first['defect_id']))
    h = auth(client)
    listing = client.get('/api/defects?kind=unscheduled&type=acmv', headers=h).get_json()
    row = next(i for i in listing['items'] if i['id'] == first['defect_id'])
    assert row['merged_count'] == 1 and row['reporter'] == 'Pat'
    assert all(i['merged_into_id'] is None for i in listing['items'])
    detail = client.get(f"/api/defects/{first['defect_id']}", headers=h).get_json()
    assert len(detail['merged_reports']) == 1 and any('Additional report' in c['text'] for c in detail['comments'])
    assert client.get('/api/defects/999999', headers=h).status_code == 404


# --- access ------------------------------------------------------------------
def test_website_approves_a_pending_request(client, master, session):
    _, m = access.request_access(9100, 'sam', 'Sam')
    h = auth(client)
    pending = client.get('/api/access/members?status=pending', headers=h).get_json()['items']
    assert any(p['id'] == m['id'] for p in pending)
    r = client.post(f"/api/access/members/{m['id']}/approve", headers=h, json={'tier': 'end_user'})
    assert r.status_code == 200 and r.get_json()['status'] == 'approved'
    assert access.by_chat(9100).decided_by == master.id
    # the bot's poller will tell Sam: notified_status still lags status until it does
    assert access.by_chat(9100).notified_status != 'approved'


def test_website_deny_revoke_reconsider_and_tier_changes(client, master, session):
    _, m = access.request_access(9101, 'a', 'A')
    h = auth(client)
    assert client.post(f"/api/access/members/{m['id']}/deny", headers=h).get_json()['status'] == 'denied'
    assert client.post(f"/api/access/members/{m['id']}/reconsider", headers=h).get_json()['status'] == 'pending'
    client.post(f"/api/access/members/{m['id']}/approve", headers=h, json={})
    assert client.patch(f"/api/access/members/{m['id']}", headers=h, json={'tier': 'master_control'}).get_json()['tier'] == 'master_control'
    assert client.post(f"/api/access/members/{m['id']}/revoke", headers=h).get_json()['status'] == 'revoked'


def test_website_cannot_revoke_the_last_master(client, master, session):
    BotMember.query.filter(BotMember.id != master.id, BotMember.tier == 'master_control').delete()
    session.flush()
    r = client.post(f'/api/access/members/{master.id}/revoke', headers=auth(client))
    assert r.status_code == 400 and 'last master' in r.get_json()['error']


def test_link_a_web_user_and_bad_requests(client, master, session, world):
    tech_id = world['tech'].id
    _, m = access.request_access(9102, 'a', 'A')
    h = auth(client)
    ok = client.patch(f"/api/access/members/{m['id']}", headers=h, json={'user_id': tech_id})
    assert ok.get_json()['user_id'] == tech_id
    assert client.patch(f"/api/access/members/{m['id']}", headers=h, json={'user_id': 999999}).status_code == 400
    assert client.get('/api/access/members?status=weird', headers=h).status_code == 400
    assert client.post('/api/access/members/999999/approve', headers=h, json={}).status_code == 400


# --- equipment types ---------------------------------------------------------
def test_equipment_types_add_edit_disable(client, master, session):
    h = auth(client)
    types = client.get('/api/equipment-types', headers=h).get_json()['items']
    assert {'acmv', 'event'} <= {t['key'] for t in types}
    created = client.post('/api/equipment-types', headers=h, json={'key': 'crane', 'name': 'Tower Crane', 'emoji': '🏗'})
    assert created.status_code == 201
    tid = created.get_json()['id']
    assert client.post('/api/equipment-types', headers=h, json={'key': 'crane', 'name': 'Other'}).status_code == 400
    edited = client.patch(f'/api/equipment-types/{tid}', headers=h, json={'name': 'Crane', 'active': False}).get_json()
    assert edited['name'] == 'Crane' and edited['active'] is False
