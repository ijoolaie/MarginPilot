"""Tenant-scoped catalog and supplier pricing persistence models."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
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


class Category(Base):
    __tablename__ = "categories"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="CASCADE", name="fk_categories_tenant"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "parent_id"],
            ["categories.tenant_id", "categories.id"],
            ondelete="RESTRICT",
            name="fk_categories_parent_tenant",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_categories_tenant_id"),
        CheckConstraint("length(btrim(name)) > 0", name="name_not_blank"),
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="parent_not_self"),
        Index(
            "uq_categories_root_live_name",
            "tenant_id",
            "name",
            unique=True,
            postgresql_where=text("parent_id IS NULL AND deleted_at IS NULL"),
        ),
        Index(
            "uq_categories_child_live_name",
            "tenant_id",
            "parent_id",
            "name",
            unique=True,
            postgresql_where=text("parent_id IS NOT NULL AND deleted_at IS NULL"),
        ),
        Index("ix_categories_tenant_parent", "tenant_id", "parent_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(BigInteger)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="CASCADE", name="fk_products_tenant"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "category_id"],
            ["categories.tenant_id", "categories.id"],
            ondelete="RESTRICT",
            name="fk_products_category_tenant",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_products_tenant_id"),
        CheckConstraint("length(btrim(sku)) > 0", name="sku_not_blank"),
        CheckConstraint("length(btrim(name)) > 0", name="name_not_blank"),
        CheckConstraint("unit IN ('piece', 'kg', 'liter', 'meter', 'box')", name="unit_allowed"),
        CheckConstraint("sale_price IS NULL OR sale_price >= 0", name="sale_price_nonnegative"),
        CheckConstraint(
            "purchase_cost IS NULL OR purchase_cost >= 0", name="purchase_cost_nonnegative"
        ),
        Index(
            "uq_products_live_sku",
            "tenant_id",
            "sku",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_products_tenant_category", "tenant_id", "category_id"),
        Index("ix_products_tenant_active", "tenant_id", "is_active"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sku: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    category_id: Mapped[int | None] = mapped_column(BigInteger)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    sale_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    purchase_cost: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ProductVariant(Base):
    __tablename__ = "product_variants"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="CASCADE", name="fk_product_variants_tenant"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            ondelete="RESTRICT",
            name="fk_product_variants_product_tenant",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_product_variants_tenant_id"),
        UniqueConstraint(
            "tenant_id", "product_id", "id", name="uq_product_variants_tenant_product_id"
        ),
        CheckConstraint("jsonb_typeof(attributes) = 'object'", name="attributes_object"),
        CheckConstraint("length(btrim(sku)) > 0", name="sku_not_blank"),
        Index(
            "uq_product_variants_live_sku",
            "tenant_id",
            "sku",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_product_variants_tenant_product", "tenant_id", "product_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    product_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sku: Mapped[str] = mapped_column(String(100), nullable=False)
    attributes: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Supplier(Base):
    __tablename__ = "suppliers"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="CASCADE", name="fk_suppliers_tenant"
        ),
        UniqueConstraint("tenant_id", "id", name="uq_suppliers_tenant_id"),
        CheckConstraint("length(btrim(name)) > 0", name="name_not_blank"),
        Index("ix_suppliers_tenant_active", "tenant_id", "is_active"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    contact_name: Mapped[str | None] = mapped_column(String(160))
    phone: Mapped[str | None] = mapped_column(String(40))
    email: Mapped[str | None] = mapped_column(String(254))
    website: Mapped[str | None] = mapped_column(String(2048))
    address: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class SupplierPriceList(Base):
    __tablename__ = "supplier_price_lists"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="CASCADE", name="fk_supplier_price_lists_tenant"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "supplier_id"],
            ["suppliers.tenant_id", "suppliers.id"],
            ondelete="RESTRICT",
            name="fk_supplier_price_lists_supplier_tenant",
        ),
        ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            ondelete="RESTRICT",
            name="fk_supplier_price_lists_creator",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_supplier_price_lists_tenant_id"),
        CheckConstraint("length(btrim(title)) > 0", name="title_not_blank"),
        CheckConstraint("source IN ('manual', 'import')", name="source_allowed"),
        CheckConstraint("status IN ('draft', 'final')", name="status_allowed"),
        Index(
            "ix_supplier_price_lists_tenant_supplier_received",
            "tenant_id",
            "supplier_id",
            "received_at",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    supplier_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    received_at: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'draft'"))
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class SupplierPrice(Base):
    __tablename__ = "supplier_prices"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="CASCADE", name="fk_supplier_prices_tenant"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "price_list_id"],
            ["supplier_price_lists.tenant_id", "supplier_price_lists.id"],
            ondelete="RESTRICT",
            name="fk_supplier_prices_price_list_tenant",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            ondelete="RESTRICT",
            name="fk_supplier_prices_product_tenant",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_supplier_prices_tenant_id"),
        CheckConstraint("length(btrim(raw_name)) > 0", name="raw_name_not_blank"),
        CheckConstraint("sku IS NULL OR length(btrim(sku)) > 0", name="sku_not_blank_when_present"),
        CheckConstraint("unit_price >= 0", name="unit_price_nonnegative"),
        CheckConstraint("currency IN ('IRT', 'IRR')", name="currency_allowed"),
        CheckConstraint(
            "unit IS NULL OR unit IN ('piece', 'kg', 'liter', 'meter', 'box')",
            name="unit_allowed",
        ),
        Index(
            "uq_supplier_prices_list_sku",
            "price_list_id",
            "sku",
            unique=True,
            postgresql_where=text("sku IS NOT NULL"),
        ),
        Index(
            "uq_supplier_prices_list_raw_name_without_sku",
            "price_list_id",
            "raw_name",
            unique=True,
            postgresql_where=text("sku IS NULL"),
        ),
        Index("ix_supplier_prices_tenant_product", "tenant_id", "product_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    price_list_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    product_id: Mapped[int | None] = mapped_column(BigInteger)
    raw_name: Mapped[str] = mapped_column(String(250), nullable=False)
    sku: Mapped[str | None] = mapped_column(String(100))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ProductPriceHistory(Base):
    __tablename__ = "product_price_history"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
            name="fk_product_price_history_tenant",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            ondelete="RESTRICT",
            name="fk_product_price_history_product_tenant",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "supplier_price_id"],
            ["supplier_prices.tenant_id", "supplier_prices.id"],
            ondelete="RESTRICT",
            name="fk_product_price_history_supplier_price_tenant",
        ),
        ForeignKeyConstraint(
            ["changed_by"],
            ["users.id"],
            ondelete="SET NULL",
            name="fk_product_price_history_changed_by",
        ),
        CheckConstraint("change_type IN ('purchase', 'sale')", name="change_type_allowed"),
        CheckConstraint("source IN ('manual', 'import', 'supplier_price')", name="source_allowed"),
        CheckConstraint("new_price >= 0", name="new_price_nonnegative"),
        CheckConstraint("old_price IS NULL OR old_price >= 0", name="old_price_nonnegative"),
        CheckConstraint(
            "(source = 'supplier_price') = (supplier_price_id IS NOT NULL)",
            name="supplier_price_source_pair",
        ),
        Index(
            "ix_product_price_history_tenant_product_type_created",
            "tenant_id",
            "product_id",
            "change_type",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    product_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    change_type: Mapped[str] = mapped_column(String(16), nullable=False)
    old_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    new_price: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    changed_by: Mapped[int | None] = mapped_column(BigInteger)
    source: Mapped[str] = mapped_column(String(24), nullable=False)
    supplier_price_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
