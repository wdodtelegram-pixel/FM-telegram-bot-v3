"""track what each person has been told about their access request

Revision ID: 0008
Revises: 0007

* notified_status: the status the requester was last told about. A decision made
  in the website is delivered by the bot's poller until this matches `status`.
* masters_notified_at: when master control was told about a pending request.
Existing members are marked as already told, so nobody is messaged on upgrade.
"""
from alembic import op
import sqlalchemy as sa

revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def _cols():
    return {c['name'] for c in sa.inspect(op.get_bind()).get_columns('bot_members')}


def upgrade():
    c = _cols()
    if 'notified_status' not in c:
        op.add_column('bot_members', sa.Column('notified_status', sa.String(16), nullable=True))
        op.execute("UPDATE bot_members SET notified_status = status")
    if 'masters_notified_at' not in c:
        op.add_column('bot_members', sa.Column('masters_notified_at', sa.DateTime(), nullable=True))
        op.execute("UPDATE bot_members SET masters_notified_at = now()")


def downgrade():
    for name in ('masters_notified_at', 'notified_status'):
        if name in _cols():
            op.drop_column('bot_members', name)
