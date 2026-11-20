"""Add tenant-scoped supplier price comparison runs and matches."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d4f5a6b7c8d9"
down_revision: str | None = "c0d1e2f3a4b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "comparison_runs",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("base_list_id", sa.BigInteger(), nullable=False),
        sa.Column("target_list_id", sa.BigInteger(), nullable=False),
        sa.Column("match_strategy", sa.String(24), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("summary", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="CASCADE", name="fk_comparison_runs_tenant"
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], ondelete="RESTRICT", name="fk_comparison_runs_creator"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "base_list_id"],
            ["supplier_price_lists.tenant_id", "supplier_price_lists.id"],
            ondelete="RESTRICT",
            name="fk_comparison_runs_base_list_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "target_list_id"],
            ["supplier_price_lists.tenant_id", "supplier_price_lists.id"],
            ondelete="RESTRICT",
            name="fk_comparison_runs_target_list_tenant",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_comparison_runs_tenant_id"),
        sa.CheckConstraint(
            "base_list_id <> target_list_id", name=op.f("ck_comparison_runs_different_price_lists")
        ),
        sa.CheckConstraint(
            "match_strategy IN ('sku', 'normalized_name', 'sku_then_name')",
            name=op.f("ck_comparison_runs_match_strategy_allowed"),
        ),
        sa.CheckConstraint(
            "status IN ('completed', 'pending_confirmation')",
            name=op.f("ck_comparison_runs_status_allowed"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(summary) = 'object'", name=op.f("ck_comparison_runs_summary_object")
        ),
    )
    op.create_index(
        "ix_comparison_runs_tenant_created_at", "comparison_runs", ["tenant_id", "created_at"]
    )
    op.create_index("ix_comparison_runs_created_by", "comparison_runs", ["created_by"])
    op.create_index(
        "ix_comparison_runs_tenant_base_list", "comparison_runs", ["tenant_id", "base_list_id"]
    )
    op.create_index(
        "ix_comparison_runs_tenant_target_list", "comparison_runs", ["tenant_id", "target_list_id"]
    )

    op.create_table(
        "comparison_matches",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("base_price_id", sa.BigInteger()),
        sa.Column("target_price_id", sa.BigInteger()),
        sa.Column("base_raw_name", sa.String(250)),
        sa.Column("target_raw_name", sa.String(250)),
        sa.Column("match_type", sa.String(16), nullable=False),
        sa.Column("suggested_product_id", sa.BigInteger()),
        sa.Column("confirmed_product_id", sa.BigInteger()),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("price_delta", sa.Numeric(20, 2)),
        sa.Column("price_delta_pct", sa.Numeric(26, 4)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="CASCADE", name="fk_comparison_matches_tenant"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            ["comparison_runs.tenant_id", "comparison_runs.id"],
            ondelete="CASCADE",
            name="fk_comparison_matches_run_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "base_price_id"],
            ["supplier_prices.tenant_id", "supplier_prices.id"],
            ondelete="RESTRICT",
            name="fk_comparison_matches_base_price_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "target_price_id"],
            ["supplier_prices.tenant_id", "supplier_prices.id"],
            ondelete="RESTRICT",
            name="fk_comparison_matches_target_price_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "suggested_product_id"],
            ["products.tenant_id", "products.id"],
            ondelete="RESTRICT",
            name="fk_comparison_matches_suggested_product_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "confirmed_product_id"],
            ["products.tenant_id", "products.id"],
            ondelete="RESTRICT",
            name="fk_comparison_matches_confirmed_product_tenant",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_comparison_matches_tenant_id"),
        sa.CheckConstraint(
            "base_price_id IS NOT NULL OR target_price_id IS NOT NULL",
            name=op.f("ck_comparison_matches_at_least_one_price"),
        ),
        sa.CheckConstraint(
            "match_type IN ('exact_sku', 'exact_name', 'uncertain', 'unmatched')",
            name=op.f("ck_comparison_matches_match_type_allowed"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'confirmed', 'rejected')",
            name=op.f("ck_comparison_matches_status_allowed"),
        ),
        sa.CheckConstraint(
            "price_delta_pct IS NULL OR price_delta IS NOT NULL",
            name=op.f("ck_comparison_matches_percentage_requires_delta"),
        ),
    )
    op.create_index(
        "ix_comparison_matches_tenant_run_status",
        "comparison_matches",
        ["tenant_id", "run_id", "status"],
    )
    op.create_index(
        "ix_comparison_matches_tenant_base_price",
        "comparison_matches",
        ["tenant_id", "base_price_id"],
        postgresql_where=sa.text("base_price_id IS NOT NULL"),
    )
    op.create_index(
        "ix_comparison_matches_tenant_target_price",
        "comparison_matches",
        ["tenant_id", "target_price_id"],
        postgresql_where=sa.text("target_price_id IS NOT NULL"),
    )
    op.create_index(
        "ix_comparison_matches_tenant_suggested_product",
        "comparison_matches",
        ["tenant_id", "suggested_product_id"],
        postgresql_where=sa.text("suggested_product_id IS NOT NULL"),
    )
    op.create_index(
        "ix_comparison_matches_tenant_confirmed_product",
        "comparison_matches",
        ["tenant_id", "confirmed_product_id"],
        postgresql_where=sa.text("confirmed_product_id IS NOT NULL"),
    )
    op.create_index(
        "uq_comparison_matches_run_base_price",
        "comparison_matches",
        ["tenant_id", "run_id", "base_price_id"],
        unique=True,
        postgresql_where=sa.text("base_price_id IS NOT NULL"),
    )
    op.create_index(
        "uq_comparison_matches_run_target_price",
        "comparison_matches",
        ["tenant_id", "run_id", "target_price_id"],
        unique=True,
        postgresql_where=sa.text("target_price_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_comparison_matches_tenant_confirmed_product", table_name="comparison_matches"
    )
    op.drop_index(
        "ix_comparison_matches_tenant_suggested_product", table_name="comparison_matches"
    )
    op.drop_index("ix_comparison_matches_tenant_target_price", table_name="comparison_matches")
    op.drop_index("ix_comparison_matches_tenant_base_price", table_name="comparison_matches")
    op.drop_index("uq_comparison_matches_run_target_price", table_name="comparison_matches")
    op.drop_index("uq_comparison_matches_run_base_price", table_name="comparison_matches")
    op.drop_index("ix_comparison_matches_tenant_run_status", table_name="comparison_matches")
    op.drop_table("comparison_matches")
    op.drop_index("ix_comparison_runs_tenant_created_at", table_name="comparison_runs")
    op.drop_index("ix_comparison_runs_tenant_target_list", table_name="comparison_runs")
    op.drop_index("ix_comparison_runs_tenant_base_list", table_name="comparison_runs")
    op.drop_index("ix_comparison_runs_created_by", table_name="comparison_runs")
    op.drop_table("comparison_runs")
