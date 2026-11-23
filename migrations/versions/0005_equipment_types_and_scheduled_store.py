"""equipment types (editable), merged scheduled store, richer defect reports

Revision ID: 0005
Revises: 0004

* equipment_types: the editable list of categories, seeded with the five
  trades plus "Event". Event is a category beside ACMV and Lift, not a separate
  store.
* maintenance_jobs (the merged scheduled store: scheduled maintenance and
  events) gains a start-to-end timeline and a link to its equipment type.
* defects (the reports store) gains what the guided report flow collects: a
  kind (scheduled/unscheduled), ONE occurrence time (no end), location,
  specific equipment, the scheduled job it matched, and the report it was
  merged into.

Existing rows are backfilled so nothing is left half-described.
"""
from alembic import op
import sqlalchemy as sa

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None

SEED = [
    ('acmv', 'ACMV', 'ACMV servicing', '❄️', 10),
    ('lift', 'Lift & Escalator', 'Lift and escalator servicing', '🛗', 20),
    ('electrical', 'Electrical', 'Electrical maintenance', '⚡', 30),
    ('fire', 'Fire Protection', 'Fire protection services', '🧯', 40),
    ('plumbing', 'Plumbing & Sanitary', 'Plumbing and sanitary services', '🚰', 50),
    ('event', 'Event', 'Events and one-off scheduled items', '📌', 60),
]


def _cols(table):
    return {c['name'] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade():
    bind = op.get_bind()

    if not sa.inspect(bind).has_table('equipment_types'):
        op.create_table(
            'equipment_types',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('key', sa.String(32), nullable=False),
            sa.Column('name', sa.String(64), nullable=False),
            sa.Column('blurb', sa.String(), nullable=True),
            sa.Column('emoji', sa.String(8), nullable=True),
            sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint('key', name='uq_equipment_types_key'),
            sa.UniqueConstraint('name', name='uq_equipment_types_name'),
        )
    for key, name, blurb, emoji, order in SEED:
        bind.execute(sa.text(
            "INSERT INTO equipment_types (key, name, blurb, emoji, sort_order) "
            "SELECT :k, :n, :b, :e, :o WHERE NOT EXISTS "
            "(SELECT 1 FROM equipment_types WHERE key = :k OR name = :n)"),
            {'k': key, 'n': name, 'b': blurb, 'e': emoji, 'o': order})

    jobs = _cols('maintenance_jobs')
    if 'starts_at' not in jobs:
        op.add_column('maintenance_jobs', sa.Column('starts_at', sa.DateTime(), nullable=True))
    if 'ends_at' not in jobs:
        op.add_column('maintenance_jobs', sa.Column('ends_at', sa.DateTime(), nullable=True))
    if 'equipment_type_id' not in jobs:
        op.add_column('maintenance_jobs', sa.Column(
            'equipment_type_id', sa.Integer(),
            sa.ForeignKey('equipment_types.id', name='fk_jobs_equipment_type'), nullable=True))
        op.create_index('ix_maintenance_jobs_equipment_type_id', 'maintenance_jobs', ['equipment_type_id'])
    # Backfill: type from the stored category name, timeline from the old dates.
    bind.execute(sa.text(
        "UPDATE maintenance_jobs j SET equipment_type_id = t.id "
        "FROM equipment_types t WHERE j.equipment_type_id IS NULL AND lower(j.category) = lower(t.name)"))
    bind.execute(sa.text(
        "UPDATE maintenance_jobs SET ends_at = estimated_completion::timestamp "
        "WHERE ends_at IS NULL AND estimated_completion IS NOT NULL"))
    bind.execute(sa.text(
        "UPDATE maintenance_jobs SET starts_at = COALESCE(next_job_date, estimated_completion)::timestamp "
        "WHERE starts_at IS NULL AND COALESCE(next_job_date, estimated_completion) IS NOT NULL"))

    d = _cols('defects')
    adds = [
        ('kind', sa.Column('kind', sa.String(16), nullable=False, server_default='unscheduled')),
        ('occurred_at', sa.Column('occurred_at', sa.DateTime(), nullable=True)),
        ('equipment_type_id', sa.Column('equipment_type_id', sa.Integer(),
                                        sa.ForeignKey('equipment_types.id', name='fk_defects_equipment_type'),
                                        nullable=True)),
        ('location', sa.Column('location', sa.String(), nullable=True)),
        ('specific_equipment', sa.Column('specific_equipment', sa.String(), nullable=True)),
        ('maintenance_job_id', sa.Column('maintenance_job_id', sa.Integer(),
                                         sa.ForeignKey('maintenance_jobs.id', name='fk_defects_job'),
                                         nullable=True)),
        ('merged_into_id', sa.Column('merged_into_id', sa.Integer(),
                                     sa.ForeignKey('defects.id', name='fk_defects_merged_into'),
                                     nullable=True)),
    ]
    for name, col in adds:
        if name not in d:
            op.add_column('defects', col)
    bind.execute(sa.text("UPDATE defects SET occurred_at = created_at WHERE occurred_at IS NULL"))
    bind.execute(sa.text(
        "UPDATE defects SET kind = 'scheduled' WHERE maintenance_job_id IS NOT NULL AND kind <> 'scheduled'"))


def downgrade():
    for name in ('merged_into_id', 'maintenance_job_id', 'specific_equipment', 'location',
                 'equipment_type_id', 'occurred_at', 'kind'):
        if name in _cols('defects'):
            op.drop_column('defects', name)
    for name in ('equipment_type_id', 'ends_at', 'starts_at'):
        if name in _cols('maintenance_jobs'):
            op.drop_column('maintenance_jobs', name)
    op.execute('DROP TABLE IF EXISTS equipment_types')
