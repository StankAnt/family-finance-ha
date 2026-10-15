"""Phase 4 FX, mortgage, valuation and goals.

Revision ID: 7b4e831a921d
Revises: 2c90be82f76e
"""
from alembic import op
import sqlalchemy as sa

revision = "7b4e831a921d"
down_revision = "2c90be82f76e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("fx_rate",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("pln_per_unit", sa.Numeric(20, 8), nullable=False),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("currency", "effective_date", "source"))
    op.create_table("mortgage",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("household_id", sa.Uuid(), sa.ForeignKey("household.id"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.UniqueConstraint("household_id", "name"))
    op.create_table("mortgage_allocation",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("mortgage_id", sa.Uuid(), sa.ForeignKey("mortgage.id"), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), sa.ForeignKey("transaction.id"), nullable=False, unique=True),
        sa.Column("principal", sa.Numeric(20, 4), nullable=False),
        sa.Column("interest", sa.Numeric(20, 4), nullable=False),
        sa.Column("fees", sa.Numeric(20, 4), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("valuation_snapshot",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("household_id", sa.Uuid(), sa.ForeignKey("household.id"), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(20, 4), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("estimated", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("household_id", "kind", "name", "as_of"))
    op.create_table("goal",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("household_id", sa.Uuid(), sa.ForeignKey("household.id"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("target_amount", sa.Numeric(20, 4), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("household_id", "name"))
    op.create_table("goal_progress",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("goal_id", sa.Uuid(), sa.ForeignKey("goal.id"), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(20, 4), nullable=False),
        sa.Column("estimated", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("goal_id", "as_of"))
    op.create_table("coverage_declaration",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("household_id", sa.Uuid(), sa.ForeignKey("household.id"), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("accounts_complete", sa.Boolean(), nullable=False),
        sa.Column("assets_complete", sa.Boolean(), nullable=False),
        sa.Column("liabilities_complete", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("household_id", "as_of"))


def downgrade() -> None:
    for name in ("coverage_declaration", "goal_progress", "goal", "valuation_snapshot", "mortgage_allocation", "mortgage", "fx_rate"):
        op.drop_table(name)
