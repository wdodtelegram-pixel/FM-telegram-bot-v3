"""
Tests run against a real PostgreSQL: the bot depends on native enums, ON
CONFLICT-free atomic UPDATEs and NULLS LAST ordering, none of which SQLite
reproduces faithfully.

    TEST_DATABASE_URL=postgresql://postgres@localhost:55432/bdms_test pytest

The database must already carry the API's migrations (flask db upgrade) and the
bot's (alembic -c migrations/alembic.ini upgrade head). Every test runs in a
transaction that is rolled back, so the database is left as it was found.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

URL = os.environ.get('TEST_DATABASE_URL')
if not URL:
    pytest.skip('set TEST_DATABASE_URL to run the bot tests', allow_module_level=True)

os.environ['DATABASE_URL'] = URL

from botapp import db as dbmod                       # noqa: E402
from botapp.models import Building, User            # noqa: E402


@pytest.fixture()
def session():
    engine = dbmod.init_engine(URL)
    conn = engine.connect()
    outer = conn.begin()
    # Bind the scoped session to this connection; commit() inside the code under
    # test then only releases a SAVEPOINT, and the outer rollback undoes it all.
    dbmod.Session.configure(bind=conn, join_transaction_mode='create_savepoint')
    dbmod.Session.remove()
    yield dbmod.Session
    dbmod.Session.remove()
    outer.rollback()
    conn.close()
    dbmod.Session.configure(bind=engine, join_transaction_mode='conservative_savepoint')


def _web_user(session, name, role):
    """The bot never creates web accounts, so the tests insert them in SQL."""
    from sqlalchemy import text
    uid = session.execute(text(
        "INSERT INTO users (name, email, password_hash, role) "
        "VALUES (:n, :e, 'x', CAST(:r AS user_roles)) RETURNING id"),
        {'n': name, 'e': f'{name.replace(" ", "").lower()}@test.invalid', 'r': role}).scalar()
    return User.query.get(uid)


@pytest.fixture()
def world(session):
    """A building, a web technician and a web CSR."""
    b = Building(name='Tower A', address='1 Test Rd')
    session.add(b)
    session.flush()
    return {'building': b,
            'tech': _web_user(session, 'Tina Tech', 'technician'),
            'csr': _web_user(session, 'Carl CSR', 'csr')}
