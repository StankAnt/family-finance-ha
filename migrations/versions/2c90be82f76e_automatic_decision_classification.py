"""Track automatically applied Decisions categories and their audit source.

Revision ID: 2c90be82f76e
Revises: 0a422d66fc9d
"""

from alembic import op
import sqlalchemy as sa

revision = "2c90be82f76e"
down_revision = "0a422d66fc9d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("classification_correction", sa.Column(
        "source", sa.String(20), nullable=False, server_default="manual"))
    op.add_column("decision_suggestion", sa.Column(
        "purchase_probability", sa.Numeric(6, 5), nullable=True))
    op.add_column("decision_suggestion", sa.Column(
        "applied_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("decision_suggestion", "applied_at")
    op.drop_column("decision_suggestion", "purchase_probability")
    op.drop_column("classification_correction", "source")
