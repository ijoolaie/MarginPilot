"""Tenant-scoped sales orders, line items and immutable returns."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Identity,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base


class SalesOrder(Base):
    __tablename__ = "sales_orders"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="CASCADE", name="fk_sales_orders_tenant"
        ),
        ForeignKeyConstraint(
            ["created_by"], ["users.id"], ondelete="RESTRICT", name="fk_sales_orders_creator"
        ),
        UniqueConstraint("tenant_id", "id", name="uq_sales_orders_tenant_id"),
        UniqueConstraint("tenant_id", "order_number", name="uq_sales_orders_tenant_order_number"),
        CheckConstraint("length(btrim(order_number)) > 0", name="order_number_not_blank"),
        CheckConstraint(
            "status IN ('pending', 'confirmed', 'processing', 'completed', 'cancelled')",
            name="status_allowed",
        ),
        CheckConstraint(
            "payment_status IN ('unpaid', 'paid', 'refunded', 'partially_refunded')",
            name="payment_status_allowed",
        ),
        CheckConstraint(
            "shipping_status IN ('not_shipped', 'shipped', 'delivered', 'returned')",
            name="shipping_status_allowed",
        ),
        CheckConstraint("currency IN ('IRT', 'IRR')", name="currency_allowed"),
        CheckConstraint("order_discount >= 0", name="order_discount_nonnegative"),
        Index("ix_sales_orders_tenant_order_date", "tenant_id", "order_date"),
        Index("ix_sales_orders_tenant_status", "tenant_id", "status"),
        Index("ix_sales_orders_created_by", "created_by"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    order_number: Mapped[str] = mapped_column(String(100), nullable=False)
    order_date: Mapped[date] = mapped_column(Date, nullable=False)
    channel: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, server_default=text("'pending'")
    )
    payment_status: Mapped[str] = mapped_column(
        String(24), nullable=False, server_default=text("'unpaid'")
    )
    shipping_status: Mapped[str] = mapped_column(
        String(24), nullable=False, server_default=text("'not_shipped'")
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    order_discount: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), nullable=False, server_default=text("0")
    )
    customer_name: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class SaleItem(Base):
    __tablename__ = "sale_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="CASCADE", name="fk_sale_items_tenant"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "order_id"],
            ["sales_orders.tenant_id", "sales_orders.id"],
            ondelete="CASCADE",
            name="fk_sale_items_order_tenant",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            ondelete="RESTRICT",
            name="fk_sale_items_product_tenant",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "variant_id"],
            ["product_variants.tenant_id", "product_variants.product_id", "product_variants.id"],
            ondelete="RESTRICT",
            name="fk_sale_items_variant_product_tenant",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_sale_items_tenant_id"),
        CheckConstraint("length(btrim(sku_snapshot)) > 0", name="sku_snapshot_not_blank"),
        CheckConstraint("length(btrim(name_snapshot)) > 0", name="name_snapshot_not_blank"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price >= 0", name="unit_price_nonnegative"),
        CheckConstraint("line_discount >= 0", name="line_discount_nonnegative"),
        CheckConstraint("order_discount_share >= 0", name="order_discount_share_nonnegative"),
        CheckConstraint("unit_cost IS NULL OR unit_cost >= 0", name="unit_cost_nonnegative"),
        CheckConstraint(
            "cost_source IN ('explicit', 'product_current', 'supplier_latest', 'unknown')",
            name="cost_source_allowed",
        ),
        CheckConstraint(
            "variant_id IS NULL OR product_id IS NOT NULL", name="variant_requires_product"
        ),
        CheckConstraint(
            "returned_quantity >= 0 AND returned_quantity <= quantity",
            name="returned_quantity_range",
        ),
        CheckConstraint("refund_amount >= 0", name="refund_amount_nonnegative"),
        Index("ix_sale_items_tenant_order", "tenant_id", "order_id"),
        Index(
            "ix_sale_items_tenant_product",
            "tenant_id",
            "product_id",
            postgresql_where=text("product_id IS NOT NULL"),
        ),
        Index(
            "ix_sale_items_tenant_variant",
            "tenant_id",
            "product_id",
            "variant_id",
            postgresql_where=text("variant_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    order_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    product_id: Mapped[int | None] = mapped_column(BigInteger)
    variant_id: Mapped[int | None] = mapped_column(BigInteger)
    sku_snapshot: Mapped[str] = mapped_column(String(100), nullable=False)
    name_snapshot: Mapped[str] = mapped_column(String(200), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    line_discount: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), nullable=False, server_default=text("0")
    )
    order_discount_share: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), nullable=False, server_default=text("0")
    )
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    cost_source: Mapped[str] = mapped_column(
        String(24), nullable=False, server_default=text("'unknown'")
    )
    returned_quantity: Mapped[Decimal] = mapped_column(
        Numeric(12, 3), nullable=False, server_default=text("0")
    )
    refund_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), nullable=False, server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class SalesReturn(Base):
    __tablename__ = "sales_returns"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="CASCADE", name="fk_sales_returns_tenant"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "order_id"],
            ["sales_orders.tenant_id", "sales_orders.id"],
            ondelete="RESTRICT",
            name="fk_sales_returns_order_tenant",
        ),
        ForeignKeyConstraint(
            ["created_by"], ["users.id"], ondelete="RESTRICT", name="fk_sales_returns_creator"
        ),
        UniqueConstraint("tenant_id", "id", name="uq_sales_returns_tenant_id"),
        UniqueConstraint(
            "tenant_id", "return_number", name="uq_sales_returns_tenant_return_number"
        ),
        CheckConstraint("length(btrim(return_number)) > 0", name="return_number_not_blank"),
        CheckConstraint("status = 'committed'", name="status_committed"),
        CheckConstraint("jsonb_typeof(refund_metadata) = 'object'", name="refund_metadata_object"),
        Index("ix_sales_returns_tenant_order", "tenant_id", "order_id"),
        Index("ix_sales_returns_created_by", "created_by"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    return_number: Mapped[str] = mapped_column(String(100), nullable=False)
    order_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    return_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'committed'")
    )
    refund_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SalesReturnItem(Base):
    __tablename__ = "sales_return_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="CASCADE", name="fk_sales_return_items_tenant"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "return_id"],
            ["sales_returns.tenant_id", "sales_returns.id"],
            ondelete="CASCADE",
            name="fk_sales_return_items_return_tenant",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "sale_item_id"],
            ["sale_items.tenant_id", "sale_items.id"],
            ondelete="RESTRICT",
            name="fk_sales_return_items_sale_item_tenant",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_sales_return_items_tenant_id"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("refund_amount >= 0", name="refund_amount_nonnegative"),
        CheckConstraint("length(btrim(sku_snapshot)) > 0", name="sku_snapshot_not_blank"),
        CheckConstraint("length(btrim(name_snapshot)) > 0", name="name_snapshot_not_blank"),
        Index("ix_sales_return_items_tenant_return", "tenant_id", "return_id"),
        Index("ix_sales_return_items_tenant_sale_item", "tenant_id", "sale_item_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    return_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sale_item_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    refund_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    sku_snapshot: Mapped[str] = mapped_column(String(100), nullable=False)
    name_snapshot: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SalesRefund(Base):
    __tablename__ = "sales_refunds"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="CASCADE", name="fk_sales_refunds_tenant"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "order_id"],
            ["sales_orders.tenant_id", "sales_orders.id"],
            ondelete="RESTRICT",
            name="fk_sales_refunds_order_tenant",
        ),
        ForeignKeyConstraint(
            ["created_by"], ["users.id"], ondelete="RESTRICT", name="fk_sales_refunds_creator"
        ),
        UniqueConstraint("tenant_id", "id", name="uq_sales_refunds_tenant_id"),
        UniqueConstraint(
            "tenant_id", "refund_number", name="uq_sales_refunds_tenant_refund_number"
        ),
        CheckConstraint("length(btrim(refund_number)) > 0", name="refund_number_not_blank"),
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("currency IN ('IRT', 'IRR')", name="currency_allowed"),
        CheckConstraint("status = 'committed'", name="status_committed"),
        Index("ix_sales_refunds_tenant_order", "tenant_id", "order_id"),
        Index("ix_sales_refunds_created_by", "created_by"),
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    refund_number: Mapped[str] = mapped_column(String(100), nullable=False)
    order_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    refund_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'committed'")
    )
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
