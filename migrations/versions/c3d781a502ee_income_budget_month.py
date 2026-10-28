"""Optional budget month for income, independent of bank dates."""
from alembic import op
import sqlalchemy as sa

revision = "c3d781a502ee"
down_revision = "b9026e17c410"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("transaction", sa.Column("income_month", sa.Date(), nullable=True))


def downgrade():
    op.drop_column("transaction", "income_month")
