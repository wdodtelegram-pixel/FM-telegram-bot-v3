import pytest

from core import equipment
from core.fm import catalog
from core.models import EquipmentType, MaintenanceJob


@pytest.fixture(autouse=True)
def restore_catalog():
    """catalog is process-wide state; put it back so tests stay independent."""
    saved = {k: dict(v) for k, v in catalog.CATEGORIES.items()}
    yield
    catalog.CATEGORIES.clear()
    catalog.CATEGORIES.update(saved)
    catalog.CATEGORY_NAMES[:] = [m['name'] for m in catalog.CATEGORIES.values()]
    catalog.KEY_BY_NAME.clear()
    catalog.KEY_BY_NAME.update({m['name']: k for k, m in catalog.CATEGORIES.items()})


def test_seeded_with_five_trades_and_event(session):
    keys = [t.key for t in equipment.list_types()]
    assert keys[:5] == ['acmv', 'lift', 'electrical', 'fire', 'plumbing'] and 'event' in keys


def test_load_catalog_refreshes_in_place_and_includes_event(session):
    same_dict = catalog.CATEGORIES
    assert equipment.load_catalog() >= 6
    assert same_dict is catalog.CATEGORIES and 'event' in catalog.CATEGORIES
    assert catalog.category_key('Event') == 'event'


def test_add_on_type_appears_in_the_catalog(session):
    equipment.create_type('crane', 'Tower Crane', 'Crane servicing', '🏗')
    equipment.load_catalog()
    assert catalog.CATEGORIES['crane']['name'] == 'Tower Crane'
    assert catalog.resolve_category('crane') == 'Tower Crane'


@pytest.mark.parametrize('key', ['', 'A', '1abc', 'has space', 'x' * 40])
def test_bad_keys_rejected(session, key):
    with pytest.raises(equipment.EquipmentError):
        equipment.create_type(key, 'Whatever')


def test_duplicates_rejected_case_insensitively(session):
    with pytest.raises(equipment.EquipmentError):
        equipment.create_type('ACMV', 'Something')
    with pytest.raises(equipment.EquipmentError):
        equipment.create_type('hvac', 'acmv')


def test_rename_keeps_jobs_in_step(session):
    t = equipment.get_by_key_or_name('plumbing')
    job = MaintenanceJob(job_ref='REN-1', category=t.name, equipment_type_id=t.id, description='x',
                         location='y', maintenance_type='Preventive', status='Yet to Start')
    session.add(job); session.flush()
    equipment.update_type(t.id, name='Plumbing, Water & Sanitary')
    assert MaintenanceJob.query.filter_by(job_ref='REN-1').one().category == 'Plumbing, Water & Sanitary'


def test_disabled_type_leaves_the_catalog_but_not_the_table(session):
    t = equipment.get_by_key_or_name('fire')
    equipment.update_type(t.id, active=False)
    equipment.load_catalog()
    assert 'fire' not in catalog.CATEGORIES
    assert EquipmentType.query.filter_by(key='fire').one().active is False


def test_empty_catalog_never_wipes_the_defaults():
    before = set(catalog.CATEGORIES)
    catalog.replace_categories({})
    assert set(catalog.CATEGORIES) == before
