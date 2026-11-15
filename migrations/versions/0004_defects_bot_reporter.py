"""let a defect be reported by someone with no web account

Revision ID: 0004
Revises: 0003

This bot is its own application and must not depend on the web app shipping a
matching migration first. Defects it raises for people without a web account
need three things on the shared `defects` table:

* `reporter_id` nullable (it was NOT NULL);
* `bot_reporter_id` and `reporter_label` to record who raised it;
* a CHECK that somebody is always recorded.

Everything is checked before it is changed, so this is safe to run on a
database where another migration (for example the BMS platform's
f6a7b8c9d0e1) has already made the same change, and in either order.
"""
from alembic import op
import sqlalchemy as sa

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None

CHECK_NAME = 'ck_defects_has_reporter'


def _columns():
    return {c['name']: c for c in sa.inspect(op.get_bind()).get_columns('defects')}


def _has_check():
    checks = sa.inspect(op.get_bind()).get_check_constraints('defects')
    return any(c['name'] == CHECK_NAME for c in checks)


def upgrade():
    cols = _columns()
    if 'bot_reporter_id' not in cols:
        op.add_column('defects', sa.Column('bot_reporter_id', sa.Integer(), nullable=True))
    if 'reporter_label' not in cols:
        op.add_column('defects', sa.Column('reporter_label', sa.String(), nullable=True))
    if not cols['reporter_id']['nullable']:
        op.alter_column('defects', 'reporter_id', existing_type=sa.Integer(), nullable=True)
    if not _has_check():
        op.create_check_constraint(
            CHECK_NAME, 'defects', 'reporter_id IS NOT NULL OR bot_reporter_id IS NOT NULL')


def downgrade():
    # Deliberately a no-op. These columns may have been created by the web
    # app's own migration, and rows raised by the bot have no reporter_id, so
    # restoring NOT NULL would fail or destroy data. Leaving them is harmless.
    pass
