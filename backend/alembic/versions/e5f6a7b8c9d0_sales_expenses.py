"""Create tenant-scoped sales, immutable returns and expenses."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e5f6a7b8c9d0"
down_revision: str | None = "d4f5a6b7c8d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sales_orders",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("order_number", sa.String(100), nullable=False),
        sa.Column("order_date", sa.Date(), nullable=False),
        sa.Column("channel", sa.String(80)),
        sa.Column("status", sa.String(24), server_default=sa.text("'pending'"), nullable=False),
        sa.Column(
            "payment_status", sa.String(24), server_default=sa.text("'unpaid'"), nullable=False
        ),
        sa.Column(
            "shipping_status",
            sa.String(24),
            server_default=sa.text("'not_shipped'"),
            nullable=False,
        ),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("order_discount", sa.Numeric(20, 2), server_default=sa.text("0"), nullable=False),
        sa.Column("customer_name", sa.String(200)),
        sa.Column("notes", sa.Text()),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="CASCADE", name="fk_sales_orders_tenant"
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], ondelete="RESTRICT", name="fk_sales_orders_creator"
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_sales_orders_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id", "order_number", name="uq_sales_orders_tenant_order_number"
        ),
        sa.CheckConstraint(
            "length(btrim(order_number)) > 0", name=op.f("ck_sales_orders_order_number_not_blank")
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'confirmed', 'processing', 'completed', 'cancelled')",
            name=op.f("ck_sales_orders_status_allowed"),
        ),
        sa.CheckConstraint(
            "payment_status IN ('unpaid', 'paid', 'refunded', 'partially_refunded')",
            name=op.f("ck_sales_orders_payment_status_allowed"),
        ),
        sa.CheckConstraint(
            "shipping_status IN ('not_shipped', 'shipped', 'delivered', 'returned')",
            name=op.f("ck_sales_orders_shipping_status_allowed"),
        ),
        sa.CheckConstraint(
            "currency IN ('IRT', 'IRR')", name=op.f("ck_sales_orders_currency_allowed")
        ),
        sa.CheckConstraint(
            "order_discount >= 0", name=op.f("ck_sales_orders_order_discount_nonnegative")
        ),
    )
    op.create_index(
        "ix_sales_orders_tenant_order_date", "sales_orders", ["tenant_id", "order_date"]
    )
    op.create_index("ix_sales_orders_tenant_status", "sales_orders", ["tenant_id", "status"])
    op.create_index("ix_sales_orders_created_by", "sales_orders", ["created_by"])

    op.create_table(
        "sale_items",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("product_id", sa.BigInteger()),
        sa.Column("variant_id", sa.BigInteger()),
        sa.Column("sku_snapshot", sa.String(100), nullable=False),
        sa.Column("name_snapshot", sa.String(200), nullable=False),
        sa.Column("quantity", sa.Numeric(12, 3), nullable=False),
        sa.Column("unit_price", sa.Numeric(20, 2), nullable=False),
        sa.Column("line_discount", sa.Numeric(20, 2), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "order_discount_share", sa.Numeric(20, 2), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("unit_cost", sa.Numeric(20, 2)),
        sa.Column(
            "cost_source", sa.String(24), server_default=sa.text("'unknown'"), nullable=False
        ),
        sa.Column(
            "returned_quantity", sa.Numeric(12, 3), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("refund_amount", sa.Numeric(20, 2), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="CASCADE", name="fk_sale_items_tenant"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "order_id"],
            ["sales_orders.tenant_id", "sales_orders.id"],
            ondelete="CASCADE",
            name="fk_sale_items_order_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            ondelete="RESTRICT",
            name="fk_sale_items_product_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "product_id", "variant_id"],
            ["product_variants.tenant_id", "product_variants.product_id", "product_variants.id"],
            ondelete="RESTRICT",
            name="fk_sale_items_variant_product_tenant",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_sale_items_tenant_id"),
        sa.CheckConstraint(
            "length(btrim(sku_snapshot)) > 0", name=op.f("ck_sale_items_sku_snapshot_not_blank")
        ),
        sa.CheckConstraint(
            "length(btrim(name_snapshot)) > 0", name=op.f("ck_sale_items_name_snapshot_not_blank")
        ),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_sale_items_quantity_positive")),
        sa.CheckConstraint("unit_price >= 0", name=op.f("ck_sale_items_unit_price_nonnegative")),
        sa.CheckConstraint(
            "line_discount >= 0", name=op.f("ck_sale_items_line_discount_nonnegative")
        ),
        sa.CheckConstraint(
            "order_discount_share >= 0", name=op.f("ck_sale_items_order_discount_share_nonnegative")
        ),
        sa.CheckConstraint(
            "unit_cost IS NULL OR unit_cost >= 0", name=op.f("ck_sale_items_unit_cost_nonnegative")
        ),
        sa.CheckConstraint(
            "cost_source IN ('explicit', 'product_current', 'supplier_latest', 'unknown')",
            name=op.f("ck_sale_items_cost_source_allowed"),
        ),
        sa.CheckConstraint(
            "variant_id IS NULL OR product_id IS NOT NULL",
            name=op.f("ck_sale_items_variant_requires_product"),
        ),
        sa.CheckConstraint(
            "returned_quantity >= 0 AND returned_quantity <= quantity",
            name=op.f("ck_sale_items_returned_quantity_range"),
        ),
        sa.CheckConstraint(
            "refund_amount >= 0", name=op.f("ck_sale_items_refund_amount_nonnegative")
        ),
    )
    op.create_index("ix_sale_items_tenant_order", "sale_items", ["tenant_id", "order_id"])
    op.create_index(
        "ix_sale_items_tenant_product",
        "sale_items",
        ["tenant_id", "product_id"],
        postgresql_where=sa.text("product_id IS NOT NULL"),
    )
    op.create_index(
        "ix_sale_items_tenant_variant",
        "sale_items",
        ["tenant_id", "product_id", "variant_id"],
        postgresql_where=sa.text("variant_id IS NOT NULL"),
    )

    op.create_table(
        "sales_returns",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("return_number", sa.String(100), nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("return_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(16), server_default=sa.text("'committed'"), nullable=False),
        sa.Column(
            "refund_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("notes", sa.Text()),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="CASCADE", name="fk_sales_returns_tenant"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "order_id"],
            ["sales_orders.tenant_id", "sales_orders.id"],
            ondelete="RESTRICT",
            name="fk_sales_returns_order_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], ondelete="RESTRICT", name="fk_sales_returns_creator"
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_sales_returns_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id", "return_number", name="uq_sales_returns_tenant_return_number"
        ),
        sa.CheckConstraint(
            "length(btrim(return_number)) > 0",
            name=op.f("ck_sales_returns_return_number_not_blank"),
        ),
        sa.CheckConstraint("status = 'committed'", name=op.f("ck_sales_returns_status_committed")),
        sa.CheckConstraint(
            "jsonb_typeof(refund_metadata) = 'object'",
            name=op.f("ck_sales_returns_refund_metadata_object"),
        ),
    )
    op.create_index("ix_sales_returns_tenant_order", "sales_returns", ["tenant_id", "order_id"])
    op.create_index("ix_sales_returns_created_by", "sales_returns", ["created_by"])

    op.create_table(
        "sales_return_items",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("return_id", sa.BigInteger(), nullable=False),
        sa.Column("sale_item_id", sa.BigInteger(), nullable=False),
        sa.Column("quantity", sa.Numeric(12, 3), nullable=False),
        sa.Column("refund_amount", sa.Numeric(20, 2), nullable=False),
        sa.Column("sku_snapshot", sa.String(100), nullable=False),
        sa.Column("name_snapshot", sa.String(200), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="CASCADE", name="fk_sales_return_items_tenant"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "return_id"],
            ["sales_returns.tenant_id", "sales_returns.id"],
            ondelete="CASCADE",
            name="fk_sales_return_items_return_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "sale_item_id"],
            ["sale_items.tenant_id", "sale_items.id"],
            ondelete="RESTRICT",
            name="fk_sales_return_items_sale_item_tenant",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_sales_return_items_tenant_id"),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_sales_return_items_quantity_positive")),
        sa.CheckConstraint(
            "refund_amount >= 0", name=op.f("ck_sales_return_items_refund_amount_nonnegative")
        ),
        sa.CheckConstraint(
            "length(btrim(sku_snapshot)) > 0",
            name=op.f("ck_sales_return_items_sku_snapshot_not_blank"),
        ),
        sa.CheckConstraint(
            "length(btrim(name_snapshot)) > 0",
            name=op.f("ck_sales_return_items_name_snapshot_not_blank"),
        ),
    )
    op.create_index(
        "ix_sales_return_items_tenant_return", "sales_return_items", ["tenant_id", "return_id"]
    )
    op.create_index(
        "ix_sales_return_items_tenant_sale_item",
        "sales_return_items",
        ["tenant_id", "sale_item_id"],
    )

    op.create_table(
        "sales_refunds",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("refund_number", sa.String(100), nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("refund_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(20, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(16), server_default=sa.text("'committed'"), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE", name="fk_sales_refunds_tenant"),
        sa.ForeignKeyConstraint(["tenant_id", "order_id"], ["sales_orders.tenant_id", "sales_orders.id"], ondelete="RESTRICT", name="fk_sales_refunds_order_tenant"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT", name="fk_sales_refunds_creator"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_sales_refunds_tenant_id"),
        sa.UniqueConstraint("tenant_id", "refund_number", name="uq_sales_refunds_tenant_refund_number"),
        sa.CheckConstraint("length(btrim(refund_number)) > 0", name=op.f("ck_sales_refunds_refund_number_not_blank")),
        sa.CheckConstraint("amount > 0", name=op.f("ck_sales_refunds_amount_positive")),
        sa.CheckConstraint("currency IN ('IRT', 'IRR')", name=op.f("ck_sales_refunds_currency_allowed")),
        sa.CheckConstraint("status = 'committed'", name=op.f("ck_sales_refunds_status_committed")),
    )
    op.create_index("ix_sales_refunds_tenant_order", "sales_refunds", ["tenant_id", "order_id"])
    op.create_index("ix_sales_refunds_created_by", "sales_refunds", ["created_by"])

    op.create_table(
        "expenses",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("expense_date", sa.Date(), nullable=False),
        sa.Column("type", sa.String(24), nullable=False),
        sa.Column("amount", sa.Numeric(20, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("allocation_scope", sa.String(16), nullable=False),
        sa.Column("order_id", sa.BigInteger()),
        sa.Column("product_id", sa.BigInteger()),
        sa.Column("period_start", sa.Date()),
        sa.Column("period_end", sa.Date()),
        sa.Column("allocation_strategy", sa.String(24)),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="CASCADE", name="fk_expenses_tenant"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "order_id"],
            ["sales_orders.tenant_id", "sales_orders.id"],
            ondelete="RESTRICT",
            name="fk_expenses_order_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            ondelete="RESTRICT",
            name="fk_expenses_product_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], ondelete="RESTRICT", name="fk_expenses_creator"
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_expenses_tenant_id"),
        sa.CheckConstraint(
            "type IN ('shipping', 'packaging', 'advertising', "
            "'payment_fee', 'operational', 'other')",
            name=op.f("ck_expenses_type_allowed"),
        ),
        sa.CheckConstraint("amount > 0", name=op.f("ck_expenses_amount_positive")),
        sa.CheckConstraint("currency IN ('IRT', 'IRR')", name=op.f("ck_expenses_currency_allowed")),
        sa.CheckConstraint(
            "allocation_scope IN ('order', 'product', 'period')",
            name=op.f("ck_expenses_allocation_scope_allowed"),
        ),
        sa.CheckConstraint(
            "(allocation_scope = 'order' AND order_id IS NOT NULL AND product_id IS NULL "
            "AND period_start IS NULL AND period_end IS NULL) OR "
            "(allocation_scope = 'product' AND product_id IS NOT NULL AND order_id IS NULL "
            "AND period_start IS NULL AND period_end IS NULL) OR "
            "(allocation_scope = 'period' AND order_id IS NULL AND product_id IS NULL "
            "AND period_start IS NOT NULL AND period_end IS NOT NULL "
            "AND period_start <= period_end)",
            name=op.f("ck_expenses_allocation_scope_fields_consistent"),
        ),
        sa.CheckConstraint(
            "allocation_strategy IS NULL OR allocation_strategy IN "
            "('revenue_share', 'equal_quantity', 'equal_count')",
            name=op.f("ck_expenses_allocation_strategy_allowed"),
        ),
    )
    op.create_index("ix_expenses_tenant_expense_date", "expenses", ["tenant_id", "expense_date"])
    op.create_index(
        "ix_expenses_tenant_type_scope", "expenses", ["tenant_id", "type", "allocation_scope"]
    )
    op.create_index(
        "ix_expenses_tenant_order",
        "expenses",
        ["tenant_id", "order_id"],
        postgresql_where=sa.text("order_id IS NOT NULL"),
    )
    op.create_index(
        "ix_expenses_tenant_product",
        "expenses",
        ["tenant_id", "product_id"],
        postgresql_where=sa.text("product_id IS NOT NULL"),
    )
    op.create_index("ix_expenses_created_by", "expenses", ["created_by"])


def downgrade() -> None:
    op.drop_index("ix_expenses_created_by", table_name="expenses")
    op.drop_index("ix_expenses_tenant_product", table_name="expenses")
    op.drop_index("ix_expenses_tenant_order", table_name="expenses")
    op.drop_index("ix_expenses_tenant_type_scope", table_name="expenses")
    op.drop_index("ix_expenses_tenant_expense_date", table_name="expenses")
    op.drop_table("expenses")

    op.drop_index("ix_sales_refunds_created_by", table_name="sales_refunds")
    op.drop_index("ix_sales_refunds_tenant_order", table_name="sales_refunds")
    op.drop_table("sales_refunds")

    op.drop_index("ix_sales_return_items_tenant_sale_item", table_name="sales_return_items")
    op.drop_index("ix_sales_return_items_tenant_return", table_name="sales_return_items")
    op.drop_table("sales_return_items")

    op.drop_index("ix_sales_returns_created_by", table_name="sales_returns")
    op.drop_index("ix_sales_returns_tenant_order", table_name="sales_returns")
    op.drop_table("sales_returns")

    op.drop_index("ix_sale_items_tenant_variant", table_name="sale_items")
    op.drop_index("ix_sale_items_tenant_product", table_name="sale_items")
    op.drop_index("ix_sale_items_tenant_order", table_name="sale_items")
    op.drop_table("sale_items")

    op.drop_index("ix_sales_orders_created_by", table_name="sales_orders")
    op.drop_index("ix_sales_orders_tenant_status", table_name="sales_orders")
    op.drop_index("ix_sales_orders_tenant_order_date", table_name="sales_orders")
    op.drop_table("sales_orders")
