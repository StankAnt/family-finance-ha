"""Store cash amounts in their original currency.

Revision ID: a439901e2b11
Revises: e6218ae5a779
"""
from alembic import op
import sqlalchemy as sa

revision = "a439901e2b11"
down_revision = "e6218ae5a779"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cash_entry", sa.Column("currency", sa.String(3), nullable=False,
                                          server_default="PLN"))


def downgrade() -> None:
    op.drop_column("cash_entry", "currency")
