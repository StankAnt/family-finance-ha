"""Add local PLN cash wallet.

Revision ID: e6218ae5a779
Revises: c45e33ba8102
"""
from alembic import op
import sqlalchemy as sa

revision = "e6218ae5a779"
down_revision = "c45e33ba8102"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("cash_entry",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("household_id", sa.Uuid(), sa.ForeignKey("household.id"), nullable=False),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(20, 4), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), sa.ForeignKey("transaction.id")),
        sa.Column("category_id", sa.Uuid(), sa.ForeignKey("category.id")),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("project.id")),
        sa.Column("note", sa.String(250)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_cash_entry_household_date", "cash_entry", ["household_id", "occurred_on"])


def downgrade() -> None:
    op.drop_index("ix_cash_entry_household_date", table_name="cash_entry")
    op.drop_table("cash_entry")
