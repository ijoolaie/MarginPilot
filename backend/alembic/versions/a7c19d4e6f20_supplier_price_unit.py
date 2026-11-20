"""Add explicit unit semantics to supplier price rows."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7c19d4e6f20"
down_revision: str | None = "f2e7b9429cbe"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("supplier_prices", sa.Column("unit", sa.String(length=20), nullable=True))
    op.create_check_constraint(
        "unit_allowed",
        "supplier_prices",
        "unit IS NULL OR unit IN ('piece', 'kg', 'liter', 'meter', 'box')",
    )


def downgrade() -> None:
    op.drop_constraint("unit_allowed", "supplier_prices", type_="check")
    op.drop_column("supplier_prices", "unit")
