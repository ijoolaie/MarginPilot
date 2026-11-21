"""Immutable calculation journal records."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Identity,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base


class Calculation(Base):
    __tablename__ = "calculations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="CASCADE", name="fk_calculations_tenant"
        ),
        ForeignKeyConstraint(
            ["created_by"], ["users.id"], ondelete="SET NULL", name="fk_calculations_creator"
        ),
        UniqueConstraint("tenant_id", "id", name="uq_calculations_tenant_id"),
        CheckConstraint(
            "calc_type IN ('sale_item', 'order', 'product', 'period', 'price_suggestion')",
            name="calc_type_allowed",
        ),
        CheckConstraint("length(btrim(formula_version)) > 0", name="formula_version_not_blank"),
        CheckConstraint("jsonb_typeof(input) = 'object'", name="input_object"),
        CheckConstraint("jsonb_typeof(output) = 'object'", name="output_object"),
        CheckConstraint("jsonb_typeof(warnings) = 'array'", name="warnings_array"),
        CheckConstraint("length(input_hash) = 64", name="input_hash_sha256"),
        CheckConstraint("source IN ('system', 'report', 'manual')", name="source_allowed"),
        Index("ix_calculations_tenant_type_created", "tenant_id", "calc_type", "created_at"),
        Index("ix_calculations_tenant_hash", "tenant_id", "input_hash"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    calc_type: Mapped[str] = mapped_column(String(24), nullable=False)
    formula_version: Mapped[str] = mapped_column(String(16), nullable=False)
    input: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    output: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    warnings: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'system'"))
    created_by: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
