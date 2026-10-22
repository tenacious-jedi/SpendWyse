"""add unique constraint on tag_rules to dedup identical rules

Revision ID: c91a7e2d4f68
Revises: b8d4f6a12c35
Create Date: 2026-10-21 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c91a7e2d4f68'
down_revision = 'b8d4f6a12c35'
branch_labels = None
depends_on = None


def upgrade():
    # The endpoint previously allowed duplicates, so collapse any existing ones
    # (keep the lowest id per group) before the constraint can be added.
    op.execute(
        """
        DELETE FROM tag_rules a
        USING tag_rules b
        WHERE a.id > b.id
          AND a.user_id = b.user_id
          AND a.tag_id = b.tag_id
          AND a.match_type = b.match_type
          AND a.match_value = b.match_value
        """
    )
    op.create_unique_constraint(
        'uq_tag_rule_dedup',
        'tag_rules',
        ['user_id', 'tag_id', 'match_type', 'match_value'],
    )


def downgrade():
    op.drop_constraint('uq_tag_rule_dedup', 'tag_rules', type_='unique')
