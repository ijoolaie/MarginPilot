"""Tenant-scoped supplier price comparison persistence models."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Identity,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base


class ComparisonRun(Base):
    """Immutable snapshot of a comparison between two finalized price lists."""

    __tablename__ = "comparison_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="CASCADE", name="fk_comparison_runs_tenant"
        ),
        ForeignKeyConstraint(
            ["created_by"], ["users.id"], ondelete="RESTRICT", name="fk_comparison_runs_creator"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "base_list_id"],
            ["supplier_price_lists.tenant_id", "supplier_price_lists.id"],
            ondelete="RESTRICT",
            name="fk_comparison_runs_base_list_tenant",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "target_list_id"],
            ["supplier_price_lists.tenant_id", "supplier_price_lists.id"],
            ondelete="RESTRICT",
            name="fk_comparison_runs_target_list_tenant",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_comparison_runs_tenant_id"),
        CheckConstraint("base_list_id <> target_list_id", name="different_price_lists"),
        CheckConstraint(
            "match_strategy IN ('sku', 'normalized_name', 'sku_then_name')",
            name="match_strategy_allowed",
        ),
        CheckConstraint("status IN ('completed', 'pending_confirmation')", name="status_allowed"),
        CheckConstraint("jsonb_typeof(summary) = 'object'", name="summary_object"),
        Index("ix_comparison_runs_tenant_created_at", "tenant_id", "created_at"),
        Index("ix_comparison_runs_created_by", "created_by"),
        Index("ix_comparison_runs_tenant_base_list", "tenant_id", "base_list_id"),
        Index("ix_comparison_runs_tenant_target_list", "tenant_id", "target_list_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    base_list_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    target_list_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    match_strategy: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ComparisonMatch(Base):
    """One matched pair, one unmatched line, or one ambiguous line."""

    __tablename__ = "comparison_matches"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="CASCADE", name="fk_comparison_matches_tenant"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            ["comparison_runs.tenant_id", "comparison_runs.id"],
            ondelete="CASCADE",
            name="fk_comparison_matches_run_tenant",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "base_price_id"],
            ["supplier_prices.tenant_id", "supplier_prices.id"],
            ondelete="RESTRICT",
            name="fk_comparison_matches_base_price_tenant",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "target_price_id"],
            ["supplier_prices.tenant_id", "supplier_prices.id"],
            ondelete="RESTRICT",
            name="fk_comparison_matches_target_price_tenant",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "suggested_product_id"],
            ["products.tenant_id", "products.id"],
            ondelete="RESTRICT",
            name="fk_comparison_matches_suggested_product_tenant",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "confirmed_product_id"],
            ["products.tenant_id", "products.id"],
            ondelete="RESTRICT",
            name="fk_comparison_matches_confirmed_product_tenant",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_comparison_matches_tenant_id"),
        CheckConstraint(
            "base_price_id IS NOT NULL OR target_price_id IS NOT NULL", name="at_least_one_price"
        ),
        CheckConstraint(
            "match_type IN ('exact_sku', 'exact_name', 'uncertain', 'unmatched')",
            name="match_type_allowed",
        ),
        CheckConstraint("status IN ('pending', 'confirmed', 'rejected')", name="status_allowed"),
        CheckConstraint(
            "price_delta_pct IS NULL OR price_delta IS NOT NULL", name="percentage_requires_delta"
        ),
        Index("ix_comparison_matches_tenant_run_status", "tenant_id", "run_id", "status"),
        Index(
            "ix_comparison_matches_tenant_base_price",
            "tenant_id",
            "base_price_id",
            postgresql_where=text("base_price_id IS NOT NULL"),
        ),
        Index(
            "ix_comparison_matches_tenant_target_price",
            "tenant_id",
            "target_price_id",
            postgresql_where=text("target_price_id IS NOT NULL"),
        ),
        Index(
            "ix_comparison_matches_tenant_suggested_product",
            "tenant_id",
            "suggested_product_id",
            postgresql_where=text("suggested_product_id IS NOT NULL"),
        ),
        Index(
            "ix_comparison_matches_tenant_confirmed_product",
            "tenant_id",
            "confirmed_product_id",
            postgresql_where=text("confirmed_product_id IS NOT NULL"),
        ),
        Index(
            "uq_comparison_matches_run_base_price",
            "tenant_id",
            "run_id",
            "base_price_id",
            unique=True,
            postgresql_where=text("base_price_id IS NOT NULL"),
        ),
        Index(
            "uq_comparison_matches_run_target_price",
            "tenant_id",
            "run_id",
            "target_price_id",
            unique=True,
            postgresql_where=text("target_price_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    run_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    base_price_id: Mapped[int | None] = mapped_column(BigInteger)
    target_price_id: Mapped[int | None] = mapped_column(BigInteger)
    base_raw_name: Mapped[str | None] = mapped_column(String(250))
    target_raw_name: Mapped[str | None] = mapped_column(String(250))
    match_type: Mapped[str] = mapped_column(String(16), nullable=False)
    suggested_product_id: Mapped[int | None] = mapped_column(BigInteger)
    confirmed_product_id: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'pending'")
    )
    price_delta: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    price_delta_pct: Mapped[Decimal | None] = mapped_column(Numeric(26, 4))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
