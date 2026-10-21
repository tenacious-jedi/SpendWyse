"""widen processed_events.event_id for external provider ids

Revision ID: b8d4f6a12c35
Revises: a7c3e5901f24
Create Date: 2026-10-20 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b8d4f6a12c35'
down_revision = 'a7c3e5901f24'
branch_labels = None
depends_on = None


def upgrade():
    # Stripe (and other provider) event ids can exceed the 36 chars sized for
    # our uuids; widen so webhook dedup can store them.
    op.alter_column(
        'processed_events',
        'event_id',
        existing_type=sa.String(length=36),
        type_=sa.String(length=255),
        existing_nullable=False,
    )


def downgrade():
    op.alter_column(
        'processed_events',
        'event_id',
        existing_type=sa.String(length=255),
        type_=sa.String(length=36),
        existing_nullable=False,
    )
