"""bot identity and notification tables

Revision ID: 0001
Revises:

Creates only what the bot owns. The shared tables (users, defects, ...) belong
to the web API's migrations; this requires them to exist because bot_members
references users.id.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None

ROLES = ('admin', 'csr', 'building_executive', 'technician')


def upgrade():
    bot_roles = postgresql.ENUM(*ROLES, name='bot_roles', create_type=False)
    bot_roles.create(op.get_bind(), checkfirst=True)

    op.create_table(
        'bot_invites',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('role', bot_roles, nullable=False),
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
        'bot_members',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('telegram_chat_id', sa.BigInteger(), nullable=False),
        sa.Column('telegram_username', sa.String(), nullable=True),
        sa.Column('display_name', sa.String(), nullable=False),
        sa.Column('role', bot_roles, nullable=False),
        sa.Column('status', sa.String(16), nullable=False, server_default='active'),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('invite_id', sa.Integer(), sa.ForeignKey('bot_invites.id'), nullable=True),
        sa.Column('joined_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('telegram_chat_id', name='uq_bot_members_telegram_chat_id'),
    )
    op.create_index('ix_bot_members_user_id', 'bot_members', ['user_id'])
    op.create_table(
        'bot_auth_attempts',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('chat_id', sa.BigInteger(), nullable=False),
        sa.Column('at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_bot_auth_attempts_chat_id', 'bot_auth_attempts', ['chat_id'])
    op.create_table(
        'bot_notification_log',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('kind', sa.String(16), nullable=False),
        sa.Column('ref_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('delivered_at', sa.DateTime(), nullable=True),
        sa.Column('last_error', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('kind', 'ref_id', 'user_id', name='uq_bot_notification'),
    )


def downgrade():
    op.drop_table('bot_notification_log')
    op.drop_index('ix_bot_auth_attempts_chat_id', table_name='bot_auth_attempts')
    op.drop_table('bot_auth_attempts')
    op.drop_index('ix_bot_members_user_id', table_name='bot_members')
    op.drop_table('bot_members')
    op.drop_table('bot_invites')
    op.execute('DROP TYPE IF EXISTS bot_roles')
