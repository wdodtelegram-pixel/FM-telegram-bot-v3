"""drop roles: every bot member is an admin

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None

ROLES = ('admin', 'csr', 'building_executive', 'technician')


def upgrade():
    op.drop_column('bot_members', 'role')
    op.drop_column('bot_invites', 'role')
    op.execute('DROP TYPE IF EXISTS bot_roles')


def downgrade():
    bot_roles = postgresql.ENUM(*ROLES, name='bot_roles', create_type=False)
    bot_roles.create(op.get_bind(), checkfirst=True)
    # Everyone was an admin, so that is what they go back to.
    op.add_column('bot_invites', sa.Column('role', bot_roles, nullable=False, server_default='admin'))
    op.add_column('bot_members', sa.Column('role', bot_roles, nullable=False, server_default='admin'))
