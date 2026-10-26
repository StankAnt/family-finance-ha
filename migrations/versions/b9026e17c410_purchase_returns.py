"""Shared purchases, bank returns and optional cash wallet movement."""
from alembic import op
import sqlalchemy as sa

revision = "b9026e17c410"
down_revision = "a439901e2b11"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("purchase_share",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("purchase_id", sa.Uuid(), sa.ForeignKey("transaction.id"), nullable=False),
        sa.Column("person", sa.String(120), nullable=False),
        sa.Column("amount", sa.Numeric(20, 4), nullable=False),
        sa.UniqueConstraint("purchase_id", "person"))
    op.create_table("purchase_link",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("purchase_id", sa.Uuid(), sa.ForeignKey("transaction.id"), nullable=False),
        sa.Column("credit_id", sa.Uuid(), sa.ForeignKey("transaction.id"), nullable=False, unique=True),
        sa.Column("share_id", sa.Uuid(), sa.ForeignKey("purchase_share.id")),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("old_economic_type", sa.String(40), nullable=False),
        sa.Column("old_category_id", sa.Uuid()), sa.Column("old_project_id", sa.Uuid()),
        sa.Column("old_override_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_purchase_link_purchase_id", "purchase_link", ["purchase_id"])
    op.add_column("cash_entry", sa.Column("share_id", sa.Uuid(), sa.ForeignKey("purchase_share.id", name="cash_entry_share_id_fkey")))
    op.add_column("cash_entry", sa.Column("affects_wallet", sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade():
    op.drop_column("cash_entry", "affects_wallet")
    op.drop_constraint("cash_entry_share_id_fkey", "cash_entry", type_="foreignkey")
    op.drop_column("cash_entry", "share_id")
    op.drop_table("purchase_link")
    op.drop_table("purchase_share")
