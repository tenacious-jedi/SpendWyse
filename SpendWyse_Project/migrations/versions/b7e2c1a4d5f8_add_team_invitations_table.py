"""add team_invitations table

Revision ID: b7e2c1a4d5f8
Revises: d9f1e42a3b56
Create Date: 2026-08-08 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b7e2c1a4d5f8'
down_revision = 'd9f1e42a3b56'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('team_invitations',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('team_id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('status', sa.Enum('pending', 'accepted', 'revoked', name='invitationstatus'), nullable=False),
    sa.Column('invited_by_id', sa.Integer(), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('accepted_user_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['team_id'], ['teams.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['invited_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['accepted_user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('team_invitations', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_team_invitations_team_id'), ['team_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_team_invitations_email'), ['email'], unique=False)
        batch_op.create_index(batch_op.f('ix_team_invitations_token_hash'), ['token_hash'], unique=True)


def downgrade():
    with op.batch_alter_table('team_invitations', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_team_invitations_token_hash'))
        batch_op.drop_index(batch_op.f('ix_team_invitations_email'))
        batch_op.drop_index(batch_op.f('ix_team_invitations_team_id'))

    op.drop_table('team_invitations')
    # Drop the enum type explicitly (Postgres does not remove it with the table).
    sa.Enum(name='invitationstatus').drop(op.get_bind(), checkfirst=True)
