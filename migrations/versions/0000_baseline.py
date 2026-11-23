"""baseline: the tables the platform shares, created only if they are missing

Revision ID: 0000
Revises:

This application owns its whole schema. On a database that already carries the
web app's tables (an existing BMS database) this does nothing. On an empty
database it creates them with the same names and columns, so the bot, the API
and the website all have somewhere to read and write.

Revisions 0001-0004 were written when the web app was assumed to have created
these tables; this baseline is inserted in front of them. Databases already
past 0001 never run it.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0000'
down_revision = None
branch_labels = None
depends_on = None


def _enum(name, *values):
    e = postgresql.ENUM(*values, name=name, create_type=False)
    e.create(op.get_bind(), checkfirst=True)
    return e


def upgrade():
    insp = sa.inspect(op.get_bind())
    has = insp.has_table

    user_roles = _enum('user_roles', 'admin', 'csr', 'building_executive', 'technician')
    d_status = _enum('defect_statuses', 'Open', 'Reviewed', 'Ongoing', 'Done', 'Completed')
    d_prio = _enum('defect_priorities', 'low', 'medium', 'high')
    m_type = _enum('maintenance_types', 'Preventive', 'Corrective')
    m_status = _enum('maintenance_statuses', 'Yet to Start', 'In Progress', 'Completed')

    if not has('users'):
        op.create_table(
            'users',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('name', sa.String(), nullable=False),
            sa.Column('email', sa.String(), nullable=False, unique=True),
            sa.Column('password_hash', sa.String(), nullable=False),
            sa.Column('role', user_roles, nullable=False),
            sa.Column('created_at', sa.DateTime()),
            sa.Column('updated_at', sa.DateTime()),
        )
    if not has('buildings'):
        op.create_table(
            'buildings',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('name', sa.String(), nullable=False),
            sa.Column('address', sa.String(), nullable=False),
            sa.Column('created_at', sa.DateTime()),
            sa.Column('updated_at', sa.DateTime()),
        )
    if not has('defects'):
        op.create_table(
            'defects',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('title', sa.String(), nullable=False),
            sa.Column('description', sa.Text(), nullable=False),
            sa.Column('status', d_status, nullable=False, server_default='Open'),
            sa.Column('priority', d_prio, nullable=False),
            sa.Column('image_url', sa.String(), nullable=True),
            sa.Column('initial_report_image', sa.Text(), nullable=True),
            sa.Column('technician_report_image', sa.Text(), nullable=True),
            sa.Column('building_id', sa.Integer(), sa.ForeignKey('buildings.id'), nullable=False),
            sa.Column('reporter_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('reviewed_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('assigned_technician_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('external_contractor', sa.Boolean(), server_default=sa.false()),
            sa.Column('contractor_name', sa.String(), nullable=True),
            sa.Column('done_at', sa.DateTime(), nullable=True),
            sa.Column('completed_at', sa.DateTime(), nullable=True),
            sa.Column('deleted_at', sa.DateTime(), nullable=True),
            sa.Column('deleted_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('created_at', sa.DateTime()),
            sa.Column('updated_at', sa.DateTime()),
        )
    if not has('defect_comments'):
        op.create_table(
            'defect_comments',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('defect_id', sa.Integer(), sa.ForeignKey('defects.id'), nullable=False),
            sa.Column('initial_report', sa.Text(), nullable=True),
            sa.Column('executive_decision', sa.Text(), nullable=True),
            sa.Column('technician_report', sa.Text(), nullable=True),
            sa.Column('verification_report', sa.Text(), nullable=True),
            sa.Column('final_completion', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime()),
            sa.Column('updated_at', sa.DateTime()),
        )
    if not has('maintenance_jobs'):
        op.create_table(
            'maintenance_jobs',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('job_ref', sa.String(32), nullable=False, unique=True),
            sa.Column('category', sa.String(64), nullable=False),
            sa.Column('description', sa.Text(), nullable=False),
            sa.Column('location', sa.String(), nullable=False),
            sa.Column('building_id', sa.Integer(), sa.ForeignKey('buildings.id'), nullable=True),
            sa.Column('maintenance_type', m_type, nullable=False, server_default='Preventive'),
            sa.Column('status', m_status, nullable=False, server_default='Yet to Start'),
            sa.Column('estimated_completion', sa.Date(), nullable=True),
            sa.Column('next_job_date', sa.Date(), nullable=True),
            sa.Column('schedule_note', sa.String(), nullable=True),
            sa.Column('assigned_technician_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('defect_id', sa.Integer(), sa.ForeignKey('defects.id'), nullable=True),
            sa.Column('created_at', sa.DateTime()),
            sa.Column('updated_at', sa.DateTime()),
        )
        op.create_index('ix_maintenance_jobs_job_ref', 'maintenance_jobs', ['job_ref'])
        op.create_index('ix_maintenance_jobs_category', 'maintenance_jobs', ['category'])


def downgrade():
    # Never drop the shared tables: they may hold the web app's data.
    pass
