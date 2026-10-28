"""allowlist access: drop invite phrases and the join lockout

Revision ID: 0003
Revises: 0002

Access is now an allowlist of Telegram IDs managed from the command line.
Existing members stay (they are on the list); invites, the lockout log and the
per-member status/invite columns go.
"""
from alembic import op
import sqlalchemy as sa

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade():
    # A member who was 'revoked' must not become allowed by this migration.
    op.execute("DELETE FROM bot_members WHERE status <> 'active'")
    op.drop_column('bot_members', 'invite_id')
    op.drop_column('bot_members', 'status')
    op.drop_index('ix_bot_auth_attempts_chat_id', table_name='bot_auth_attempts')
    op.drop_table('bot_auth_attempts')
    op.drop_table('bot_invites')


def downgrade():
    op.create_table(
        'bot_invites',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('phrase_hash', sa.String(64), nullable=False),
        sa.Column('label', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('max_uses', sa.Integer(), nullable=True),
        sa.Column('uses', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('phrase_hash', name='uq_bot_invites_phrase_hash'),
    )
    op.create_table(
        'bot_auth_attempts',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('chat_id', sa.BigInteger(), nullable=False),
        sa.Column('at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_bot_auth_attempts_chat_id', 'bot_auth_attempts', ['chat_id'])
    op.add_column('bot_members', sa.Column('status', sa.String(16), nullable=False, server_default='active'))
    op.add_column('bot_members', sa.Column('invite_id', sa.Integer(), sa.ForeignKey('bot_invites.id'), nullable=True))
