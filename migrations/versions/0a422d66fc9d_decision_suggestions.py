"""Store reviewed Decisions API suggestions without raw external responses.

Revision ID: 0a422d66fc9d
Revises: aaa716e53082
"""

from alembic import op
import sqlalchemy as sa

revision = "0a422d66fc9d"
down_revision = "aaa716e53082"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "decision_suggestion",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=True),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("model", sa.String(80), nullable=False),
        sa.Column("confidence", sa.Numeric(6, 5), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["transaction_id"], ["transaction.id"]),
        sa.ForeignKeyConstraint(["category_id"], ["category.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("transaction_id"),
    )


def downgrade() -> None:
    op.drop_table("decision_suggestion")
