"""add idempotency_keys table

Revision ID: a7c3e5901f24
Revises: f4b1d8e63a29
Create Date: 2026-10-18 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a7c3e5901f24'
down_revision = 'f4b1d8e63a29'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('idempotency_keys',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('idempotency_key', sa.String(length=255), nullable=False),
    sa.Column('method', sa.String(length=10), nullable=False),
    sa.Column('path', sa.String(length=255), nullable=False),
    sa.Column('request_hash', sa.String(length=64), nullable=False),
    sa.Column('status_code', sa.Integer(), nullable=True),
    sa.Column('response_body', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'idempotency_key', name='uq_idempotency_user_key')
    )
    op.create_index(
        op.f('ix_idempotency_keys_user_id'),
        'idempotency_keys',
        ['user_id'],
        unique=False,
    )


def downgrade():
    op.drop_index(op.f('ix_idempotency_keys_user_id'), table_name='idempotency_keys')
    op.drop_table('idempotency_keys')
