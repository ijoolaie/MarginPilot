"""Tenant-scoped two-phase import persistence."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base


class ImportBatch(Base):
    __tablename__ = "imports"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="CASCADE", name="fk_imports_tenant"
        ),
        ForeignKeyConstraint(
            ["created_by"], ["users.id"], ondelete="RESTRICT", name="fk_imports_creator"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "supplier_id"],
            ["suppliers.tenant_id", "suppliers.id"],
            ondelete="RESTRICT",
            name="fk_imports_supplier_tenant",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_imports_tenant_id"),
        CheckConstraint("kind IN ('products', 'supplier_prices', 'sales')", name="kind_allowed"),
        CheckConstraint(
            "status IN ('uploaded', 'parsed', 'mapped', 'validated', "
            "'awaiting_confirmation', 'committed', 'failed', 'cancelled')",
            name="status_allowed",
        ),
        CheckConstraint("file_size_bytes > 0", name="file_size_positive"),
        CheckConstraint("length(btrim(file_name)) > 0", name="file_name_not_blank"),
        CheckConstraint("file_hash ~ '^[0-9a-f]{64}$'", name="file_hash_sha256"),
        CheckConstraint(
            "(kind = 'supplier_prices') = (supplier_id IS NOT NULL)",
            name="supplier_required_for_price_import",
        ),
        CheckConstraint(
            "kind <> 'supplier_prices' OR "
            "(price_list_title IS NOT NULL AND received_at IS NOT NULL)",
            name="price_list_metadata_required",
        ),
        CheckConstraint("jsonb_typeof(column_headers) = 'array'", name="headers_array"),
        CheckConstraint("jsonb_typeof(mapping) = 'object'", name="mapping_object"),
        CheckConstraint("jsonb_typeof(stats) = 'object'", name="stats_object"),
        Index("ix_imports_tenant_created_at", "tenant_id", "created_at"),
        Index("ix_imports_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    sheet_name: Mapped[str | None] = mapped_column(String(128))
    column_headers: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    mapping: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    stats: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    supplier_id: Mapped[int | None] = mapped_column(BigInteger)
    price_list_title: Mapped[str | None] = mapped_column(String(200))
    received_at: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ImportRow(Base):
    __tablename__ = "import_rows"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="CASCADE", name="fk_import_rows_tenant"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "import_id"],
            ["imports.tenant_id", "imports.id"],
            ondelete="CASCADE",
            name="fk_import_rows_import_tenant",
        ),
        UniqueConstraint(
            "tenant_id", "import_id", "row_number", name="uq_import_rows_tenant_import_row"
        ),
        CheckConstraint("row_number > 1", name="row_number_after_header"),
        CheckConstraint(
            "status IN ('pending', 'valid', 'error', 'warning', 'duplicate')",
            name="status_allowed",
        ),
        CheckConstraint("jsonb_typeof(raw) = 'object'", name="raw_object"),
        CheckConstraint(
            "normalized IS NULL OR jsonb_typeof(normalized) = 'object'", name="normalized_object"
        ),
        CheckConstraint("jsonb_typeof(errors) = 'array'", name="errors_array"),
        Index("ix_import_rows_import_status", "tenant_id", "import_id", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    import_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    normalized: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'pending'")
    )
    errors: Mapped[list[dict[str, str]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
