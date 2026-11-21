"""Create immutable calculation journal.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f6a7b8c9d0e1"
down_revision: str | None = "e5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "calculations",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("calc_type", sa.String(24), nullable=False),
        sa.Column("formula_version", sa.String(16), nullable=False),
        sa.Column("input", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("output", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "warnings",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("source", sa.String(16), server_default=sa.text("'system'"), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="CASCADE", name="fk_calculations_tenant"
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], ondelete="SET NULL", name="fk_calculations_creator"
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_calculations_tenant_id"),
        sa.CheckConstraint(
            "calc_type IN ('sale_item', 'order', 'product', 'period', 'price_suggestion')",
            name="calc_type_allowed",
        ),
        sa.CheckConstraint("length(btrim(formula_version)) > 0", name="formula_version_not_blank"),
        sa.CheckConstraint("jsonb_typeof(input) = 'object'", name="input_object"),
        sa.CheckConstraint("jsonb_typeof(output) = 'object'", name="output_object"),
        sa.CheckConstraint("jsonb_typeof(warnings) = 'array'", name="warnings_array"),
        sa.CheckConstraint("length(input_hash) = 64", name="input_hash_sha256"),
        sa.CheckConstraint("source IN ('system', 'report', 'manual')", name="source_allowed"),
    )
    op.create_index(
        "ix_calculations_tenant_type_created",
        "calculations",
        ["tenant_id", "calc_type", "created_at"],
    )
    op.create_index("ix_calculations_tenant_hash", "calculations", ["tenant_id", "input_hash"])


def downgrade() -> None:
    op.drop_index("ix_calculations_tenant_hash", table_name="calculations")
    op.drop_index("ix_calculations_tenant_type_created", table_name="calculations")
    op.drop_table("calculations")
