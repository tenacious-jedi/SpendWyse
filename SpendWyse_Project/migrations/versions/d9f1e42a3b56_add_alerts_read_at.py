"""add read_at to alerts

Revision ID: d9f1e42a3b56
Revises: c48a72f0b3d1
Create Date: 2026-07-22 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'd9f1e42a3b56'
down_revision = 'c48a72f0b3d1'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('alerts', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('read_at', sa.DateTime(timezone=True), nullable=True)
        )


def downgrade():
    with op.batch_alter_table('alerts', schema=None) as batch_op:
        batch_op.drop_column('read_at')
