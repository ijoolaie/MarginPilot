"""Tenant-scoped business expense persistence."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

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
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base


class Expense(Base):
    __tablename__ = "expenses"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="CASCADE", name="fk_expenses_tenant"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "order_id"],
            ["sales_orders.tenant_id", "sales_orders.id"],
            ondelete="RESTRICT",
            name="fk_expenses_order_tenant",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            ondelete="RESTRICT",
            name="fk_expenses_product_tenant",
        ),
        ForeignKeyConstraint(
            ["created_by"], ["users.id"], ondelete="RESTRICT", name="fk_expenses_creator"
        ),
        UniqueConstraint("tenant_id", "id", name="uq_expenses_tenant_id"),
        CheckConstraint(
            "type IN ('shipping', 'packaging', 'advertising', '"
            "payment_fee', 'operational', 'other')",
            name="type_allowed",
        ),
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("currency IN ('IRT', 'IRR')", name="currency_allowed"),
        CheckConstraint(
            "allocation_scope IN ('order', 'product', 'period')", name="allocation_scope_allowed"
        ),
        CheckConstraint(
            "(allocation_scope = 'order' AND order_id IS NOT NULL AND product_id IS NULL "
            "AND period_start IS NULL AND period_end IS NULL) OR "
            "(allocation_scope = 'product' AND product_id IS NOT NULL AND order_id IS NULL "
            "AND period_start IS NULL AND period_end IS NULL) OR "
            "(allocation_scope = 'period' AND order_id IS NULL AND product_id IS NULL "
            "AND period_start IS NOT NULL AND period_end IS NOT NULL "
            "AND period_start <= period_end)",
            name="allocation_scope_fields_consistent",
        ),
        CheckConstraint(
            "allocation_strategy IS NULL OR allocation_strategy IN "
            "('revenue_share', 'equal_quantity', 'equal_count')",
            name="allocation_strategy_allowed",
        ),
        Index("ix_expenses_tenant_expense_date", "tenant_id", "expense_date"),
        Index("ix_expenses_tenant_type_scope", "tenant_id", "type", "allocation_scope"),
        Index(
            "ix_expenses_tenant_order",
            "tenant_id",
            "order_id",
            postgresql_where=text("order_id IS NOT NULL"),
        ),
        Index(
            "ix_expenses_tenant_product",
            "tenant_id",
            "product_id",
            postgresql_where=text("product_id IS NOT NULL"),
        ),
        Index("ix_expenses_created_by", "created_by"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    expense_date: Mapped[date] = mapped_column(Date, nullable=False)
    type: Mapped[str] = mapped_column(String(24), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    allocation_scope: Mapped[str] = mapped_column(String(16), nullable=False)
    order_id: Mapped[int | None] = mapped_column(BigInteger)
    product_id: Mapped[int | None] = mapped_column(BigInteger)
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    allocation_strategy: Mapped[str | None] = mapped_column(String(24))
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
