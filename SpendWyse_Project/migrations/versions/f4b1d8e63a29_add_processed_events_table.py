"""add processed_events table

Revision ID: f4b1d8e63a29
Revises: e2a9c7d14b83
Create Date: 2026-08-30 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f4b1d8e63a29'
down_revision = 'e2a9c7d14b83'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('processed_events',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('consumer_group', sa.String(length=255), nullable=False),
    sa.Column('event_id', sa.String(length=36), nullable=False),
    sa.Column('processed_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('consumer_group', 'event_id', name='uq_processed_events_group_event')
    )


def downgrade():
    op.drop_table('processed_events')
