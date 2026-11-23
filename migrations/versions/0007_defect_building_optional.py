"""defects.building_id becomes optional

Revision ID: 0007
Revises: 0006

The guided report flow collects a free-text location, not a building. When the
location happens to name a known building the link is still made; otherwise the
defect stands on its location text alone.
"""
from alembic import op
import sqlalchemy as sa

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade():
    cols = {c['name']: c for c in sa.inspect(op.get_bind()).get_columns('defects')}
    if not cols['building_id']['nullable']:
        op.alter_column('defects', 'building_id', existing_type=sa.Integer(), nullable=True)


def downgrade():
    # Deliberately a no-op: rows created without a building would violate NOT NULL.
    pass
