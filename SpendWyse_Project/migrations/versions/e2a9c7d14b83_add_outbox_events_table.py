"""add outbox_events table

Revision ID: e2a9c7d14b83
Revises: b7e2c1a4d5f8
Create Date: 2026-08-27 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e2a9c7d14b83'
down_revision = 'b7e2c1a4d5f8'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('outbox_events',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('event_id', sa.String(length=36), nullable=False),
    sa.Column('event_type', sa.String(length=255), nullable=False),
    sa.Column('topic', sa.String(length=255), nullable=False),
    sa.Column('aggregate_key', sa.String(length=255), nullable=True),
    sa.Column('envelope', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('event_id', name='uq_outbox_events_event_id')
    )
    with op.batch_alter_table('outbox_events', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_outbox_events_published_at'), ['published_at'], unique=False)


def downgrade():
    with op.batch_alter_table('outbox_events', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_outbox_events_published_at'))

    op.drop_table('outbox_events')
