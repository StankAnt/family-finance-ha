"""Audit explicit dashboard corrections to manual finance inputs.

Revision ID: c45e33ba8102
Revises: 7b4e831a921d
"""
from alembic import op
import sqlalchemy as sa

revision = "c45e33ba8102"
down_revision = "7b4e831a921d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("manual_revision",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("household_id", sa.Uuid(), sa.ForeignKey("household.id"), nullable=False),
        sa.Column("entity_kind", sa.String(40), nullable=False),
        sa.Column("record_id", sa.Uuid(), nullable=False),
        sa.Column("previous_value", sa.Text(), nullable=False),
        sa.Column("new_value", sa.Text(), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False))


def downgrade() -> None:
    op.drop_table("manual_revision")
