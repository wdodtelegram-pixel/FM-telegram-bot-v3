"""
Equipment types: the editable list of categories (ACMV, Lift, ..., Event).

Master control edits it (website or CLI). Everything else reads it: the bot's
menus and messages, the importer, the report flow. `load_catalog()` copies the
active rows into core.fm.catalog so existing code keeps working unchanged.
"""

import re

from sqlalchemy import func

from core.db import db
from core.fm import catalog
from core.models import EquipmentType, MaintenanceJob

KEY_RE = re.compile(r'^[a-z][a-z0-9_]{1,31}$')


class EquipmentError(Exception):
    """An equipment-type request that is well-formed but cannot be satisfied."""


def load_catalog():
    """Refresh core.fm.catalog from the database. Returns how many types are live."""
    rows = (EquipmentType.query.filter_by(active=True)
            .order_by(EquipmentType.sort_order, EquipmentType.id).all())
    catalog.replace_categories({
        r.key: {'name': r.name, 'blurb': r.blurb or r.name, 'emoji': r.emoji or '▫️'}
        for r in rows
    })
    return len(rows)


def list_types(include_inactive=False):
    q = EquipmentType.query
    if not include_inactive:
        q = q.filter_by(active=True)
    return q.order_by(EquipmentType.sort_order, EquipmentType.id).all()


def serialize(t):
    return {'id': t.id, 'key': t.key, 'name': t.name, 'blurb': t.blurb, 'emoji': t.emoji,
            'sort_order': t.sort_order, 'active': t.active}


def get_by_key_or_name(value):
    text = (value or '').strip()
    if not text:
        return None
    return (EquipmentType.query.filter(func.lower(EquipmentType.key) == text.lower()).first()
            or EquipmentType.query.filter(func.lower(EquipmentType.name) == text.lower()).first())



def create_type(key, name, blurb=None, emoji=None):
    key = (key or '').strip().lower()
    name = (name or '').strip()
    if not KEY_RE.match(key):
        raise EquipmentError('The key must be 2-32 characters: a letter, then letters, digits or _')
    if not name:
        raise EquipmentError('A name is required')
    if EquipmentType.query.filter(func.lower(EquipmentType.key) == key).first():
        raise EquipmentError(f'The key "{key}" is already used')
    if EquipmentType.query.filter(func.lower(EquipmentType.name) == name.lower()).first():
        raise EquipmentError(f'The name "{name}" is already used')
    last = db.session.query(func.max(EquipmentType.sort_order)).scalar() or 0
    t = EquipmentType(key=key, name=name, blurb=(blurb or '').strip() or None,
                      emoji=(emoji or '').strip() or None, sort_order=last + 10, active=True)
    db.session.add(t)
    db.session.commit()
    return t



def update_type(type_id, name=None, blurb=None, emoji=None, active=None, sort_order=None):
    t = EquipmentType.query.get(type_id)
    if t is None:
        raise EquipmentError('No such equipment type')
    if name is not None and name.strip() and name.strip() != t.name:
        new = name.strip()
        clash = EquipmentType.query.filter(func.lower(EquipmentType.name) == new.lower(),
                                           EquipmentType.id != t.id).first()
        if clash:
            raise EquipmentError(f'The name "{new}" is already used')
        # Jobs store the type's name in `category`; keep them in step on rename.
        MaintenanceJob.query.filter(MaintenanceJob.equipment_type_id == t.id).update(
            {'category': new}, synchronize_session=False)
        t.name = new
    if blurb is not None:
        t.blurb = blurb.strip() or None
    if emoji is not None:
        t.emoji = emoji.strip() or None
    if active is not None:
        t.active = bool(active)
    if sort_order is not None:
        t.sort_order = int(sort_order)
    db.session.commit()
    return t
