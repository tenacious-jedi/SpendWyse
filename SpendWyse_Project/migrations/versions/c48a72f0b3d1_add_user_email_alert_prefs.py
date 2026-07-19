"""add alerts_email_enabled and alerts_email_min_level to users

Revision ID: c48a72f0b3d1
Revises: a131bf620619
Create Date: 2026-07-18 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'c48a72f0b3d1'
down_revision = 'a131bf620619'
branch_labels = None
depends_on = None


def upgrade():
    # The alertlevel enum type was created by the initial migration for the
    # alerts table; reuse it here rather than let SQLAlchemy try to CREATE
    # TYPE again.
    alert_level = postgresql.ENUM(
        'warn', 'alert', name='alertlevel', create_type=False
    )

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'alerts_email_enabled',
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            )
        )
        batch_op.add_column(
            sa.Column(
                'alerts_email_min_level',
                alert_level,
                nullable=False,
                server_default='warn',
            )
        )


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('alerts_email_min_level')
        batch_op.drop_column('alerts_email_enabled')
