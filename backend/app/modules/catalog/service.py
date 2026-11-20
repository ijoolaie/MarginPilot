"""Catalog domain invariants and audit helpers."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.audit.models import AuditLog
from app.modules.catalog.models import Product, ProductVariant
from app.modules.tenancy.models import Tenant


def lock_tenant(db: Session, tenant_id: int) -> Tenant:
    tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
    if tenant is None or tenant.deleted_at is not None or tenant.status != "active":
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    return tenant


def ensure_sku_available(
    db: Session,
    tenant_id: int,
    sku: str,
    *,
    exclude_product_id: int | None = None,
    exclude_variant_id: int | None = None,
) -> None:
    product_query = select(Product).where(
        Product.tenant_id == tenant_id, Product.sku == sku, Product.deleted_at.is_(None)
    )
    variant_query = select(ProductVariant.id).where(
        ProductVariant.tenant_id == tenant_id,
        ProductVariant.sku == sku,
        ProductVariant.deleted_at.is_(None),
    )
    if exclude_product_id is not None:
        product_query = product_query.where(Product.id != exclude_product_id)
    if exclude_variant_id is not None:
        variant_query = variant_query.where(ProductVariant.id != exclude_variant_id)
    if (
        db.scalar(product_query.limit(1)) is not None
        or db.scalar(variant_query.limit(1)) is not None
    ):
        raise HTTPException(status_code=409, detail="SKU_ALREADY_EXISTS")


def add_audit(
    db: Session,
    request: Request,
    *,
    user_id: int,
    tenant_id: int,
    action: str,
    entity_type: str,
    entity_id: int | str,
    detail: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditLog(
            tenant_id=tenant_id,
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id),
            detail=detail or {},
            ip=request.client.host if request.client else None,
        )
    )


def commit_or_conflict(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="RESOURCE_CONFLICT") from exc


def normalize_optional(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None


def validate_supplier_price_currency(currency: str, tenant: Tenant) -> None:
    if currency != tenant.currency_code:
        raise HTTPException(status_code=422, detail="CURRENCY_MISMATCH")


def validate_supplier_price_product(db: Session, tenant_id: int, product_id: int | None) -> None:
    if product_id is None:
        return
    product = db.scalar(
        select(Product).where(
            Product.id == product_id, Product.tenant_id == tenant_id, Product.deleted_at.is_(None)
        )
    )
    if product is None:
        raise HTTPException(status_code=404, detail="NOT_FOUND")


def record_price_change(
    db: Session,
    *,
    tenant_id: int,
    product: Product,
    change_type: str,
    new_price: Decimal,
    user_id: int,
    source: str = "manual",
    supplier_price_id: int | None = None,
) -> None:
    from app.modules.catalog.models import ProductPriceHistory

    old_price = product.purchase_cost if change_type == "purchase" else product.sale_price
    if old_price == new_price:
        return
    db.add(
        ProductPriceHistory(
            tenant_id=tenant_id,
            product_id=product.id,
            change_type=change_type,
            old_price=old_price,
            new_price=new_price,
            changed_by=user_id,
            source=source,
            supplier_price_id=supplier_price_id,
        )
    )
    if change_type == "purchase":
        product.purchase_cost = new_price
    else:
        product.sale_price = new_price


def flush_or_conflict(db: Session) -> None:
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="RESOURCE_CONFLICT") from exc
