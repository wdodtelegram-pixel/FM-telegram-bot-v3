"""access: tiers and a remembered request/approval status

Revision ID: 0006
Revises: 0005

bot_members becomes the Access store. Everyone already in it was added by an
administrator, so they become approved master control (they were admins). New
people arrive as pending end users and are decided once; the decision is kept.
"""
from alembic import op
import sqlalchemy as sa

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def _cols():
    return {c['name'] for c in sa.inspect(op.get_bind()).get_columns('bot_members')}


def upgrade():
    c = _cols()
    if 'tier' not in c:
        op.add_column('bot_members', sa.Column('tier', sa.String(16), nullable=False,
                                               server_default='end_user'))
    if 'status' not in c:
        op.add_column('bot_members', sa.Column('status', sa.String(16), nullable=False,
                                               server_default='pending'))
        # Everyone who exists now was approved by an administrator.
        op.execute("UPDATE bot_members SET tier = 'master_control', status = 'approved'")
    if 'requested_at' not in c:
        op.add_column('bot_members', sa.Column('requested_at', sa.DateTime(), nullable=True))
        op.execute("UPDATE bot_members SET requested_at = joined_at")
    if 'decided_by' not in c:
        op.add_column('bot_members', sa.Column(
            'decided_by', sa.Integer(),
            sa.ForeignKey('bot_members.id', name='fk_bot_members_decided_by'), nullable=True))
    if 'decided_at' not in c:
        op.add_column('bot_members', sa.Column('decided_at', sa.DateTime(), nullable=True))
        op.execute("UPDATE bot_members SET decided_at = joined_at WHERE status = 'approved'")
    op.create_index('ix_bot_members_status', 'bot_members', ['status'], if_not_exists=True)


def downgrade():
    op.drop_index('ix_bot_members_status', table_name='bot_members', if_exists=True)
    for name in ('decided_at', 'decided_by', 'requested_at', 'status', 'tier'):
        if name in _cols():
            op.drop_column('bot_members', name)
