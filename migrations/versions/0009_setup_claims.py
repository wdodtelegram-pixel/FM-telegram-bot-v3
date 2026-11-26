"""first-run setup claims

Revision ID: 0009
Revises: 0008

A fresh install has nobody to approve the first person. The launcher asks for an
email and password, stores only their hashes here together with a one-time code,
and the first person to send that code to the bot (/claim CODE) becomes master
control. See core/setup.py.
"""
from alembic import op
import sqlalchemy as sa

revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade():
    if sa.inspect(op.get_bind()).has_table('setup_claims'):
        return
    op.create_table(
        'setup_claims',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('code_hash', sa.String(64), nullable=False),
        sa.Column('email', sa.String(), nullable=False),
        sa.Column('password_hash', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('claimed_at', sa.DateTime(), nullable=True),
        sa.Column('claimed_by_member_id', sa.Integer(), nullable=True),
    )


def downgrade():
    op.execute('DROP TABLE IF EXISTS setup_claims')
