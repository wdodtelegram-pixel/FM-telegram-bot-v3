"""
Guards against the two deployables drifting apart.

* the mapped columns/enums must exist in the live database (the API owns them);
* the bot's vendored fm/catalog.py must match the API's copy.
"""
import importlib.util
import os

from sqlalchemy import inspect, text

from botapp import db as dbmod
from botapp.fm import catalog as bot_catalog
from botapp.models import Base

SHARED = {'users', 'buildings', 'defects', 'defect_comments', 'maintenance_jobs'}


def test_every_mapped_column_exists_in_the_database(session):
    insp = inspect(dbmod.get_engine())
    problems = []
    for table in Base.metadata.sorted_tables:
        live = {c['name']: c for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name not in live:
                problems.append(f'{table.name}.{col.name} missing')
    assert not problems, problems


def test_enum_labels_match_the_database(session):
    for table in Base.metadata.sorted_tables:
        for col in table.columns:
            enum = getattr(col.type, 'enums', None)
            name = getattr(col.type, 'name', None)
            if not enum:
                continue
            live = [r[0] for r in session.execute(text(
                "SELECT e.enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
                "WHERE t.typname = :n ORDER BY e.enumsortorder"), {'n': name})]
            assert set(enum) == set(live), f'{table.name}.{col.name} ({name}): {enum} vs {live}'


def test_bot_does_not_import_the_web_stack():
    root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'botapp')
    offenders = []
    for d, _, files in os.walk(root):
        for f in files:
            if f.endswith('.py'):
                src = open(os.path.join(d, f)).read()
                for needle in ('import flask', 'from flask', 'flask_sqlalchemy', 'from app import',
                               'from extensions', 'from routes', 'Backend'):
                    if needle in src.replace('Backend/', '').replace('the web API', ''):
                        offenders.append((f, needle))
    assert not offenders, offenders


def test_catalog_matches_the_api_copy():
    api = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                       'Backend', 'fm', 'catalog.py')
    if not os.path.exists(api):
        import pytest; pytest.skip('Backend/ not alongside Bot/ (standalone checkout)')
    spec = importlib.util.spec_from_file_location('api_catalog', api)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    assert mod.CATEGORIES == bot_catalog.CATEGORIES
    assert mod.STATUS_CANONICAL == bot_catalog.STATUS_CANONICAL
    assert mod.TYPE_CANONICAL == bot_catalog.TYPE_CANONICAL
