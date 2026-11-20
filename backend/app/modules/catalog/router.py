"""Tenant-scoped Catalog and Supplier HTTP API."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, or_, select

from app.modules.catalog.models import (
    Category,
    Product,
    ProductPriceHistory,
    ProductVariant,
    Supplier,
    SupplierPrice,
    SupplierPriceList,
)
from app.modules.catalog.service import (
    add_audit,
    commit_or_conflict,
    ensure_sku_available,
    flush_or_conflict,
    lock_tenant,
    normalize_optional,
    record_price_change,
    validate_supplier_price_currency,
    validate_supplier_price_product,
)
from app.modules.tenancy.dependencies import TenantContext, require_permission

router = APIRouter(tags=["catalog", "suppliers"])


def _clean_email(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    value = value.strip().casefold()
    local, separator, domain = value.partition("@")
    if (
        not separator
        or not local
        or not domain
        or "@" in domain
        or "." not in domain
        or any(char.isspace() for char in value)
    ):
        raise ValueError("invalid email")
    return value


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CategoryCreate(InputModel):
    name: str = Field(min_length=1, max_length=120)
    parent_id: int | None = Field(default=None, gt=0)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name cannot be blank")
        return value


class CategoryUpdate(InputModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    parent_id: int | None = Field(default=None, gt=0)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("name cannot be blank")
        return value


class ProductCreate(InputModel):
    sku: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    category_id: int | None = Field(default=None, gt=0)
    unit: Literal["piece", "kg", "liter", "meter", "box"]
    sale_price: Decimal | None = Field(default=None, ge=0, max_digits=20, decimal_places=2)
    purchase_cost: Decimal | None = Field(default=None, ge=0, max_digits=20, decimal_places=2)
    is_active: bool = True

    @field_validator("sku", "name")
    @classmethod
    def clean_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value cannot be blank")
        return value


class ProductUpdate(InputModel):
    sku: str | None = Field(default=None, min_length=1, max_length=100)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    category_id: int | None = Field(default=None, gt=0)
    unit: Literal["piece", "kg", "liter", "meter", "box"] | None = None
    sale_price: Decimal | None = Field(default=None, ge=0, max_digits=20, decimal_places=2)
    purchase_cost: Decimal | None = Field(default=None, ge=0, max_digits=20, decimal_places=2)
    is_active: bool | None = None

    @field_validator("sku", "name")
    @classmethod
    def clean_optional_required(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("value cannot be blank")
        return value


class VariantCreate(InputModel):
    sku: str = Field(min_length=1, max_length=100)
    attributes: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True

    @field_validator("sku")
    @classmethod
    def clean_sku(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("sku cannot be blank")
        return value


class SupplierCreate(InputModel):
    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        return _clean_email(value)

    name: str = Field(min_length=1, max_length=200)
    contact_name: str | None = Field(default=None, max_length=160)
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=254)
    website: str | None = Field(default=None, max_length=2048)
    address: str | None = None
    notes: str | None = None
    is_active: bool = True

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name cannot be blank")
        return value


class SupplierUpdate(InputModel):
    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        return _clean_email(value)

    name: str | None = Field(default=None, min_length=1, max_length=200)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("name cannot be blank")
        return value

    contact_name: str | None = Field(default=None, max_length=160)
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=254)
    website: str | None = Field(default=None, max_length=2048)
    address: str | None = None
    notes: str | None = None
    is_active: bool | None = None


class SupplierPriceItemInput(InputModel):
    raw_name: str = Field(min_length=1, max_length=250)
    sku: str | None = Field(default=None, max_length=100)
    product_id: int | None = Field(default=None, gt=0)
    unit_price: Decimal = Field(ge=0, max_digits=20, decimal_places=2)
    currency: Literal["IRT", "IRR"]
    unit: Literal["piece", "kg", "liter", "meter", "box"]

    @field_validator("raw_name")
    @classmethod
    def clean_raw_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("raw_name cannot be blank")
        return value

    @field_validator("sku")
    @classmethod
    def clean_optional_sku(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("sku cannot be blank")
        return value


class PriceListCreate(InputModel):
    title: str = Field(min_length=1, max_length=200)
    received_at: date
    items: list[SupplierPriceItemInput] = Field(min_length=1, max_length=5000)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("title cannot be blank")
        return value


class PurchaseCostFromSupplierInput(InputModel):
    supplier_price_id: int = Field(gt=0)


class PriceListFinalize(InputModel):
    confirm: Literal[True]


def _page(rows: list[Any], page: int, page_size: int, total: int) -> dict[str, Any]:
    return {
        "data": rows,
        "meta": {
            "page": page,
            "page_size": page_size,
            "total_items": total,
            "total_pages": (total + page_size - 1) // page_size,
        },
    }


def _category_data(row: Category) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "parent_id": row.parent_id,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _product_data(row: Product) -> dict[str, Any]:
    return {
        "id": row.id,
        "sku": row.sku,
        "name": row.name,
        "description": row.description,
        "category_id": row.category_id,
        "unit": row.unit,
        "sale_price": row.sale_price,
        "purchase_cost": row.purchase_cost,
        "is_active": row.is_active,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _supplier_data(row: Supplier) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "contact_name": row.contact_name,
        "phone": row.phone,
        "email": row.email,
        "website": row.website,
        "address": row.address,
        "notes": row.notes,
        "is_active": row.is_active,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _get_product(context: TenantContext, product_id: int) -> Product:
    row = context.auth.db.scalar(
        select(Product).where(
            Product.id == product_id,
            Product.tenant_id == context.tenant.id,
            Product.deleted_at.is_(None),
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    return row


def _get_supplier(context: TenantContext, supplier_id: int) -> Supplier:
    row = context.auth.db.scalar(
        select(Supplier).where(
            Supplier.id == supplier_id,
            Supplier.tenant_id == context.tenant.id,
            Supplier.deleted_at.is_(None),
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    return row


def _validate_category(context: TenantContext, category_id: int | None) -> None:
    if (
        category_id is not None
        and context.auth.db.scalar(
            select(Category.id).where(
                Category.id == category_id,
                Category.tenant_id == context.tenant.id,
                Category.deleted_at.is_(None),
            )
        )
        is None
    ):
        raise HTTPException(status_code=404, detail="NOT_FOUND")


def _ensure_no_category_cycle(
    context: TenantContext, category_id: int, parent_id: int | None
) -> None:
    if parent_id is None:
        return
    db, tenant_id = context.auth.db, context.tenant.id
    seen: set[int] = set()
    current: int | None = parent_id
    while current is not None:
        if current == category_id or current in seen:
            raise HTTPException(status_code=409, detail="CATEGORY_CYCLE")
        seen.add(current)
        result = db.execute(
            select(Category.id, Category.parent_id).where(
                Category.id == current,
                Category.tenant_id == tenant_id,
                Category.deleted_at.is_(None),
            )
        ).first()
        if result is None:
            raise HTTPException(status_code=404, detail="NOT_FOUND")
        current = result.parent_id


@router.get("/categories")
def list_categories(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    context: TenantContext = Depends(require_permission("product:read")),
) -> dict[str, Any]:
    db, tenant_id = context.auth.db, context.tenant.id
    base = select(Category).where(Category.tenant_id == tenant_id, Category.deleted_at.is_(None))
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(
        base.order_by(Category.parent_id.nullsfirst(), Category.name, Category.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return _page([_category_data(row) for row in rows], page, page_size, total)


@router.post("/categories", status_code=status.HTTP_201_CREATED)
def create_category(
    payload: CategoryCreate,
    request: Request,
    context: TenantContext = Depends(require_permission("product:write")),
) -> dict[str, Any]:
    db, tenant_id = context.auth.db, context.tenant.id
    lock_tenant(db, tenant_id)
    _validate_category(context, payload.parent_id)
    row = Category(tenant_id=tenant_id, name=payload.name, parent_id=payload.parent_id)
    db.add(row)
    flush_or_conflict(db)
    add_audit(
        db,
        request,
        user_id=context.auth.user.id,
        tenant_id=tenant_id,
        action="catalog.category_created",
        entity_type="category",
        entity_id=row.id,
    )
    commit_or_conflict(db)
    return {"data": _category_data(row)}


@router.patch("/categories/{category_id}")
def update_category(
    category_id: int,
    payload: CategoryUpdate,
    request: Request,
    context: TenantContext = Depends(require_permission("product:write")),
) -> dict[str, Any]:
    db, tenant_id = context.auth.db, context.tenant.id
    lock_tenant(db, tenant_id)
    row = db.scalar(
        select(Category)
        .where(
            Category.id == category_id,
            Category.tenant_id == tenant_id,
            Category.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    changes = payload.model_dump(exclude_unset=True)
    if not changes or ("name" in changes and changes["name"] is None):
        raise HTTPException(status_code=422, detail="REQUEST_INVALID")
    if "parent_id" in changes:
        _validate_category(context, changes["parent_id"])
        _ensure_no_category_cycle(context, category_id, changes["parent_id"])
    for key, value in changes.items():
        setattr(row, key, value)
    add_audit(
        db,
        request,
        user_id=context.auth.user.id,
        tenant_id=tenant_id,
        action="catalog.category_updated",
        entity_type="category",
        entity_id=row.id,
        detail={"fields": sorted(changes)},
    )
    commit_or_conflict(db)
    return {"data": _category_data(row)}


@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(
    category_id: int,
    request: Request,
    context: TenantContext = Depends(require_permission("product:write")),
) -> Response:
    db, tenant_id = context.auth.db, context.tenant.id
    lock_tenant(db, tenant_id)
    row = db.scalar(
        select(Category)
        .where(
            Category.id == category_id,
            Category.tenant_id == tenant_id,
            Category.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    child = db.scalar(
        select(Category.id)
        .where(
            Category.tenant_id == tenant_id,
            Category.parent_id == category_id,
            Category.deleted_at.is_(None),
        )
        .limit(1)
    )
    product = db.scalar(
        select(Product.id)
        .where(
            Product.tenant_id == tenant_id,
            Product.category_id == category_id,
            Product.deleted_at.is_(None),
        )
        .limit(1)
    )
    if child is not None or product is not None:
        raise HTTPException(status_code=409, detail="CATEGORY_IN_USE")
    row.deleted_at = datetime.now(UTC)
    add_audit(
        db,
        request,
        user_id=context.auth.user.id,
        tenant_id=tenant_id,
        action="catalog.category_deleted",
        entity_type="category",
        entity_id=row.id,
    )
    commit_or_conflict(db)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/products")
def list_products(
    query: str | None = Query(default=None, max_length=200),
    category_id: int | None = Query(default=None, gt=0),
    status_filter: Literal["active", "inactive"] | None = Query(default=None, alias="status"),
    supplier_id: int | None = Query(default=None, gt=0, alias="supplier"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    context: TenantContext = Depends(require_permission("product:read")),
) -> dict[str, Any]:
    db, tenant_id = context.auth.db, context.tenant.id
    base = select(Product).where(Product.tenant_id == tenant_id, Product.deleted_at.is_(None))
    if query and query.strip():
        pattern = f"%{query.strip()}%"
        base = base.where(or_(Product.name.ilike(pattern), Product.sku.ilike(pattern)))
    if category_id is not None:
        base = base.where(Product.category_id == category_id)
    if status_filter is not None:
        base = base.where(Product.is_active.is_(status_filter == "active"))
    if supplier_id is not None:
        base = (
            base.join(SupplierPrice, SupplierPrice.product_id == Product.id)
            .join(SupplierPriceList, SupplierPriceList.id == SupplierPrice.price_list_id)
            .where(
                SupplierPriceList.tenant_id == tenant_id,
                SupplierPriceList.supplier_id == supplier_id,
            )
            .distinct()
        )
    total = db.scalar(select(func.count()).select_from(base.order_by(None).subquery())) or 0
    rows = db.scalars(
        base.order_by(Product.name, Product.id).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return _page([_product_data(row) for row in rows], page, page_size, total)


@router.post("/products", status_code=status.HTTP_201_CREATED)
def create_product(
    payload: ProductCreate,
    request: Request,
    context: TenantContext = Depends(require_permission("product:write")),
) -> dict[str, Any]:
    db, tenant_id = context.auth.db, context.tenant.id
    lock_tenant(db, tenant_id)
    ensure_sku_available(db, tenant_id, payload.sku)
    _validate_category(context, payload.category_id)
    row = Product(tenant_id=tenant_id, **payload.model_dump())
    db.add(row)
    flush_or_conflict(db)
    for kind, value in (("sale", row.sale_price), ("purchase", row.purchase_cost)):
        if value is not None:
            db.add(
                ProductPriceHistory(
                    tenant_id=tenant_id,
                    product_id=row.id,
                    change_type=kind,
                    old_price=None,
                    new_price=value,
                    changed_by=context.auth.user.id,
                    source="manual",
                )
            )
    add_audit(
        db,
        request,
        user_id=context.auth.user.id,
        tenant_id=tenant_id,
        action="catalog.product_created",
        entity_type="product",
        entity_id=row.id,
    )
    commit_or_conflict(db)
    return {"data": _product_data(row)}


@router.get("/products/{product_id}")
def get_product(
    product_id: int, context: TenantContext = Depends(require_permission("product:read"))
) -> dict[str, Any]:
    product = _get_product(context, product_id)
    variants = context.auth.db.scalars(
        select(ProductVariant)
        .where(
            ProductVariant.tenant_id == context.tenant.id,
            ProductVariant.product_id == product.id,
            ProductVariant.deleted_at.is_(None),
        )
        .order_by(ProductVariant.id)
    ).all()
    return {
        "data": {
            **_product_data(product),
            "variants": [
                {"id": v.id, "sku": v.sku, "attributes": v.attributes, "is_active": v.is_active}
                for v in variants
            ],
        }
    }


@router.patch("/products/{product_id}")
def update_product(
    product_id: int,
    payload: ProductUpdate,
    request: Request,
    context: TenantContext = Depends(require_permission("product:write")),
) -> dict[str, Any]:
    db, tenant_id = context.auth.db, context.tenant.id
    lock_tenant(db, tenant_id)
    row = db.scalar(
        select(Product)
        .where(
            Product.id == product_id, Product.tenant_id == tenant_id, Product.deleted_at.is_(None)
        )
        .with_for_update()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    changes = payload.model_dump(exclude_unset=True)
    if not changes or ("name" in changes and changes["name"] is None):
        raise HTTPException(status_code=422, detail="REQUEST_INVALID")
    for field in ("sku", "name", "unit", "is_active"):
        if field in changes and changes[field] is None:
            raise HTTPException(status_code=422, detail="REQUEST_INVALID")
    for field in ("sale_price", "purchase_cost"):
        if field in changes and changes[field] is None:
            raise HTTPException(status_code=422, detail="PRICE_CANNOT_BE_CLEARED")
    if "sku" in changes:
        ensure_sku_available(db, tenant_id, str(changes["sku"]), exclude_product_id=row.id)
    if "category_id" in changes:
        _validate_category(context, changes["category_id"])
    for kind, field in (("sale", "sale_price"), ("purchase", "purchase_cost")):
        if field in changes:
            record_price_change(
                db,
                tenant_id=tenant_id,
                product=row,
                change_type=kind,
                new_price=changes[field],
                user_id=context.auth.user.id,
            )
    for key, value in changes.items():
        if key not in {"sale_price", "purchase_cost"}:
            setattr(row, key, value)
    add_audit(
        db,
        request,
        user_id=context.auth.user.id,
        tenant_id=tenant_id,
        action="catalog.product_updated",
        entity_type="product",
        entity_id=row.id,
        detail={"fields": sorted(changes)},
    )
    commit_or_conflict(db)
    return {"data": _product_data(row)}


@router.post("/products/{product_id}/purchase-cost-from-supplier-price")
def set_purchase_cost_from_supplier_price(
    product_id: int,
    payload: PurchaseCostFromSupplierInput,
    request: Request,
    context: TenantContext = Depends(require_permission("product:write")),
) -> dict[str, Any]:
    db, tenant_id = context.auth.db, context.tenant.id
    tenant = lock_tenant(db, tenant_id)
    product = db.scalar(
        select(Product)
        .where(
            Product.id == product_id, Product.tenant_id == tenant_id, Product.deleted_at.is_(None)
        )
        .with_for_update()
    )
    if product is None:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    eligible = db.execute(
        select(SupplierPrice, SupplierPriceList, Supplier)
        .join(SupplierPriceList, SupplierPriceList.id == SupplierPrice.price_list_id)
        .join(Supplier, Supplier.id == SupplierPriceList.supplier_id)
        .where(
            SupplierPrice.id == payload.supplier_price_id,
            SupplierPrice.tenant_id == tenant_id,
            SupplierPrice.product_id == product_id,
            SupplierPrice.currency == tenant.currency_code,
            SupplierPrice.unit == product.unit,
            SupplierPriceList.status == "final",
            Supplier.deleted_at.is_(None),
            Supplier.is_active.is_(True),
        )
        .with_for_update(of=SupplierPrice)
    ).first()
    if eligible is None:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    price, price_list, supplier = eligible
    record_price_change(
        db,
        tenant_id=tenant_id,
        product=product,
        change_type="purchase",
        new_price=price.unit_price,
        user_id=context.auth.user.id,
        source="supplier_price",
        supplier_price_id=price.id,
    )
    add_audit(
        db,
        request,
        user_id=context.auth.user.id,
        tenant_id=tenant_id,
        action="catalog.purchase_cost_set_from_supplier_price",
        entity_type="product",
        entity_id=product.id,
        detail={
            "supplier_price_id": price.id,
            "price_list_id": price_list.id,
            "supplier_id": supplier.id,
        },
    )
    commit_or_conflict(db)
    return {
        "data": {
            "product_id": product.id,
            "purchase_cost": product.purchase_cost,
            "currency": tenant.currency_code,
            "source": "supplier_price",
            "supplier_price_id": price.id,
        }
    }


@router.delete("/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product(
    product_id: int,
    request: Request,
    context: TenantContext = Depends(require_permission("product:write")),
) -> Response:
    db, tenant_id = context.auth.db, context.tenant.id
    lock_tenant(db, tenant_id)
    row = db.scalar(
        select(Product)
        .where(
            Product.id == product_id, Product.tenant_id == tenant_id, Product.deleted_at.is_(None)
        )
        .with_for_update()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    now = datetime.now(UTC)
    row.deleted_at, row.is_active = now, False
    db.query(ProductVariant).filter(
        ProductVariant.tenant_id == tenant_id,
        ProductVariant.product_id == product_id,
        ProductVariant.deleted_at.is_(None),
    ).update({"deleted_at": now, "is_active": False}, synchronize_session=False)
    add_audit(
        db,
        request,
        user_id=context.auth.user.id,
        tenant_id=tenant_id,
        action="catalog.product_deleted",
        entity_type="product",
        entity_id=row.id,
    )
    commit_or_conflict(db)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/products/{product_id}/price-history")
def product_price_history(
    product_id: int,
    change_type: Literal["purchase", "sale"] | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    context: TenantContext = Depends(require_permission("product:read")),
) -> dict[str, Any]:
    db, tenant_id = context.auth.db, context.tenant.id
    _get_product(context, product_id)
    base = select(ProductPriceHistory).where(
        ProductPriceHistory.tenant_id == tenant_id, ProductPriceHistory.product_id == product_id
    )
    if change_type:
        base = base.where(ProductPriceHistory.change_type == change_type)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(
        base.order_by(ProductPriceHistory.created_at.desc(), ProductPriceHistory.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return _page(
        [
            {
                "id": r.id,
                "change_type": r.change_type,
                "old_price": r.old_price,
                "new_price": r.new_price,
                "source": r.source,
                "supplier_price_id": r.supplier_price_id,
                "changed_by": r.changed_by,
                "created_at": r.created_at,
            }
            for r in rows
        ],
        page,
        page_size,
        total,
    )


@router.post("/products/{product_id}/variants", status_code=status.HTTP_201_CREATED)
def create_variant(
    product_id: int,
    payload: VariantCreate,
    request: Request,
    context: TenantContext = Depends(require_permission("product:write")),
) -> dict[str, Any]:
    db, tenant_id = context.auth.db, context.tenant.id
    lock_tenant(db, tenant_id)
    product = _get_product(context, product_id)
    ensure_sku_available(db, tenant_id, payload.sku)
    row = ProductVariant(tenant_id=tenant_id, product_id=product.id, **payload.model_dump())
    db.add(row)
    flush_or_conflict(db)
    add_audit(
        db,
        request,
        user_id=context.auth.user.id,
        tenant_id=tenant_id,
        action="catalog.variant_created",
        entity_type="product_variant",
        entity_id=row.id,
        detail={"product_id": product_id},
    )
    commit_or_conflict(db)
    return {
        "data": {
            "id": row.id,
            "product_id": row.product_id,
            "sku": row.sku,
            "attributes": row.attributes,
            "is_active": row.is_active,
            "created_at": row.created_at,
        }
    }


@router.get("/suppliers")
def list_suppliers(
    query: str | None = Query(default=None, max_length=200),
    status_filter: Literal["active", "inactive"] | None = Query(default=None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    context: TenantContext = Depends(require_permission("supplier:read")),
) -> dict[str, Any]:
    db, tenant_id = context.auth.db, context.tenant.id
    base = select(Supplier).where(Supplier.tenant_id == tenant_id, Supplier.deleted_at.is_(None))
    if query and query.strip():
        pattern = f"%{query.strip()}%"
        base = base.where(
            or_(
                Supplier.name.ilike(pattern),
                Supplier.contact_name.ilike(pattern),
                Supplier.phone.ilike(pattern),
                Supplier.email.ilike(pattern),
            )
        )
    if status_filter:
        base = base.where(Supplier.is_active.is_(status_filter == "active"))
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(
        base.order_by(Supplier.name, Supplier.id).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return _page([_supplier_data(row) for row in rows], page, page_size, total)


@router.post("/suppliers", status_code=status.HTTP_201_CREATED)
def create_supplier(
    payload: SupplierCreate,
    request: Request,
    context: TenantContext = Depends(require_permission("supplier:write")),
) -> dict[str, Any]:
    db, tenant_id = context.auth.db, context.tenant.id
    row = Supplier(tenant_id=tenant_id, **payload.model_dump())
    for field in ("contact_name", "phone", "website", "address", "notes", "email"):
        setattr(row, field, normalize_optional(getattr(row, field)))
    db.add(row)
    flush_or_conflict(db)
    add_audit(
        db,
        request,
        user_id=context.auth.user.id,
        tenant_id=tenant_id,
        action="supplier.created",
        entity_type="supplier",
        entity_id=row.id,
    )
    commit_or_conflict(db)
    return {"data": _supplier_data(row)}


@router.patch("/suppliers/{supplier_id}")
def update_supplier(
    supplier_id: int,
    payload: SupplierUpdate,
    request: Request,
    context: TenantContext = Depends(require_permission("supplier:write")),
) -> dict[str, Any]:
    db, tenant_id = context.auth.db, context.tenant.id
    row = db.scalar(
        select(Supplier)
        .where(
            Supplier.id == supplier_id,
            Supplier.tenant_id == tenant_id,
            Supplier.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    changes = payload.model_dump(exclude_unset=True)
    if not changes or ("name" in changes and changes["name"] is None):
        raise HTTPException(status_code=422, detail="REQUEST_INVALID")
    if "name" in changes and changes["name"] is None:
        raise HTTPException(status_code=422, detail="REQUEST_INVALID")
    for key, value in changes.items():
        setattr(row, key, normalize_optional(value) if isinstance(value, str) else value)
    add_audit(
        db,
        request,
        user_id=context.auth.user.id,
        tenant_id=tenant_id,
        action="supplier.updated",
        entity_type="supplier",
        entity_id=row.id,
        detail={"fields": sorted(changes)},
    )
    commit_or_conflict(db)
    return {"data": _supplier_data(row)}


@router.delete("/suppliers/{supplier_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_supplier(
    supplier_id: int,
    request: Request,
    context: TenantContext = Depends(require_permission("supplier:write")),
) -> Response:
    db, tenant_id = context.auth.db, context.tenant.id
    lock_tenant(db, tenant_id)
    row = db.scalar(
        select(Supplier)
        .where(
            Supplier.id == supplier_id,
            Supplier.tenant_id == tenant_id,
            Supplier.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    row.deleted_at, row.is_active = datetime.now(UTC), False
    add_audit(
        db,
        request,
        user_id=context.auth.user.id,
        tenant_id=tenant_id,
        action="supplier.deleted",
        entity_type="supplier",
        entity_id=row.id,
    )
    commit_or_conflict(db)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/suppliers/{supplier_id}/price-lists", status_code=status.HTTP_201_CREATED)
def create_price_list(
    supplier_id: int,
    payload: PriceListCreate,
    request: Request,
    context: TenantContext = Depends(require_permission("supplier:write")),
) -> dict[str, Any]:
    db, tenant_id = context.auth.db, context.tenant.id
    tenant = lock_tenant(db, tenant_id)
    supplier = _get_supplier(context, supplier_id)
    if not supplier.is_active:
        raise HTTPException(status_code=409, detail="SUPPLIER_INACTIVE")
    seen_skus: set[str] = set()
    seen_names: set[str] = set()
    for item in payload.items:
        validate_supplier_price_currency(item.currency, tenant)
        validate_supplier_price_product(db, tenant_id, item.product_id)
        key = item.sku if item.sku is not None else item.raw_name
        seen = seen_skus if item.sku is not None else seen_names
        if key in seen:
            raise HTTPException(status_code=409, detail="DUPLICATE_PRICE_LIST_ITEM")
        seen.add(key)
    row = SupplierPriceList(
        tenant_id=tenant_id,
        supplier_id=supplier.id,
        title=payload.title,
        received_at=payload.received_at,
        source="manual",
        status="draft",
        created_by=context.auth.user.id,
    )
    db.add(row)
    flush_or_conflict(db)
    for item in payload.items:
        db.add(
            SupplierPrice(
                tenant_id=tenant_id,
                price_list_id=row.id,
                product_id=item.product_id,
                raw_name=item.raw_name,
                sku=item.sku,
                unit_price=item.unit_price,
                currency=item.currency,
                unit=item.unit,
            )
        )
    add_audit(
        db,
        request,
        user_id=context.auth.user.id,
        tenant_id=tenant_id,
        action="supplier.price_list_created",
        entity_type="supplier_price_list",
        entity_id=row.id,
        detail={"item_count": len(payload.items)},
    )
    commit_or_conflict(db)
    return {
        "data": {
            "id": row.id,
            "supplier_id": row.supplier_id,
            "title": row.title,
            "received_at": row.received_at,
            "source": row.source,
            "status": row.status,
            "item_count": len(payload.items),
            "created_at": row.created_at,
        }
    }


@router.get("/suppliers/{supplier_id}/price-lists")
def list_price_lists(
    supplier_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    context: TenantContext = Depends(require_permission("supplier:read")),
) -> dict[str, Any]:
    db, tenant_id = context.auth.db, context.tenant.id
    _get_supplier(context, supplier_id)
    base = select(SupplierPriceList).where(
        SupplierPriceList.tenant_id == tenant_id, SupplierPriceList.supplier_id == supplier_id
    )
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(
        base.order_by(SupplierPriceList.received_at.desc(), SupplierPriceList.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return _page(
        [
            {
                "id": r.id,
                "title": r.title,
                "received_at": r.received_at,
                "source": r.source,
                "status": r.status,
                "created_at": r.created_at,
            }
            for r in rows
        ],
        page,
        page_size,
        total,
    )


@router.get("/price-lists/{price_list_id}")
def get_price_list(
    price_list_id: int, context: TenantContext = Depends(require_permission("supplier:read"))
) -> dict[str, Any]:
    db, tenant_id = context.auth.db, context.tenant.id
    row = db.scalar(
        select(SupplierPriceList).where(
            SupplierPriceList.id == price_list_id, SupplierPriceList.tenant_id == tenant_id
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    items = db.scalars(
        select(SupplierPrice)
        .where(SupplierPrice.tenant_id == tenant_id, SupplierPrice.price_list_id == row.id)
        .order_by(SupplierPrice.id)
    ).all()
    return {
        "data": {
            "id": row.id,
            "supplier_id": row.supplier_id,
            "title": row.title,
            "received_at": row.received_at,
            "source": row.source,
            "status": row.status,
            "items": [
                {
                    "id": i.id,
                    "product_id": i.product_id,
                    "raw_name": i.raw_name,
                    "sku": i.sku,
                    "unit_price": i.unit_price,
                    "currency": i.currency,
                    "unit": i.unit,
                }
                for i in items
            ],
        }
    }


@router.delete("/price-lists/{price_list_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_draft_price_list(
    price_list_id: int,
    request: Request,
    context: TenantContext = Depends(require_permission("supplier:write")),
) -> Response:
    db, tenant_id = context.auth.db, context.tenant.id
    row = db.scalar(
        select(SupplierPriceList)
        .where(SupplierPriceList.id == price_list_id, SupplierPriceList.tenant_id == tenant_id)
        .with_for_update()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    if row.status != "draft":
        raise HTTPException(status_code=409, detail="FINAL_PRICE_LIST_IMMUTABLE")
    db.query(SupplierPrice).filter(
        SupplierPrice.tenant_id == tenant_id, SupplierPrice.price_list_id == price_list_id
    ).delete(synchronize_session=False)
    db.delete(row)
    add_audit(
        db,
        request,
        user_id=context.auth.user.id,
        tenant_id=tenant_id,
        action="supplier.draft_price_list_deleted",
        entity_type="supplier_price_list",
        entity_id=price_list_id,
    )
    commit_or_conflict(db)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/price-lists/{price_list_id}/finalize")
def finalize_price_list(
    price_list_id: int,
    payload: PriceListFinalize,
    request: Request,
    context: TenantContext = Depends(require_permission("supplier:write")),
) -> dict[str, Any]:
    db, tenant_id = context.auth.db, context.tenant.id
    row = db.scalar(
        select(SupplierPriceList)
        .where(SupplierPriceList.id == price_list_id, SupplierPriceList.tenant_id == tenant_id)
        .with_for_update()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    supplier = db.scalar(
        select(Supplier)
        .where(
            Supplier.id == row.supplier_id,
            Supplier.tenant_id == tenant_id,
            Supplier.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if supplier is None or not supplier.is_active:
        raise HTTPException(status_code=409, detail="SUPPLIER_INACTIVE")
    if row.status == "final":
        raise HTTPException(status_code=409, detail="PRICE_LIST_ALREADY_FINAL")
    count = (
        db.scalar(
            select(func.count(SupplierPrice.id)).where(
                SupplierPrice.tenant_id == tenant_id, SupplierPrice.price_list_id == row.id
            )
        )
        or 0
    )
    if count == 0:
        raise HTTPException(status_code=409, detail="EMPTY_PRICE_LIST")
    row.status = "final"
    add_audit(
        db,
        request,
        user_id=context.auth.user.id,
        tenant_id=tenant_id,
        action="supplier.price_list_finalized",
        entity_type="supplier_price_list",
        entity_id=row.id,
        detail={"item_count": count},
    )
    commit_or_conflict(db)
    return {"data": {"id": row.id, "status": row.status, "item_count": count}}


@router.get("/suppliers/{supplier_id}/price-history")
def supplier_price_history(
    supplier_id: int,
    product_id: int = Query(gt=0),
    context: TenantContext = Depends(require_permission("supplier:read")),
) -> dict[str, Any]:
    db, tenant_id = context.auth.db, context.tenant.id
    _get_supplier(context, supplier_id)
    _get_product(context, product_id)
    rows = db.execute(
        select(SupplierPrice, SupplierPriceList)
        .join(SupplierPriceList, SupplierPriceList.id == SupplierPrice.price_list_id)
        .where(
            SupplierPrice.tenant_id == tenant_id,
            SupplierPrice.product_id == product_id,
            SupplierPriceList.supplier_id == supplier_id,
            SupplierPriceList.status == "final",
        )
        .order_by(SupplierPriceList.received_at, SupplierPrice.id)
    ).all()
    return {
        "data": [
            {
                "price_list_id": price_list.id,
                "received_at": price_list.received_at,
                "unit_price": price.unit_price,
                "currency": price.currency,
                "sku": price.sku,
                "raw_name": price.raw_name,
                "unit": price.unit,
            }
            for price, price_list in rows
        ]
    }


@router.get("/suppliers/lowest-price")
def lowest_supplier_price(
    product_id: int = Query(gt=0),
    context: TenantContext = Depends(require_permission("supplier:read")),
) -> dict[str, Any]:
    db, tenant_id = context.auth.db, context.tenant.id
    product = _get_product(context, product_id)
    rows = db.execute(
        select(SupplierPrice, SupplierPriceList, Supplier)
        .join(SupplierPriceList, SupplierPriceList.id == SupplierPrice.price_list_id)
        .join(Supplier, Supplier.id == SupplierPriceList.supplier_id)
        .where(
            SupplierPrice.tenant_id == tenant_id,
            SupplierPrice.product_id == product_id,
            SupplierPriceList.status == "final",
            SupplierPrice.currency == context.tenant.currency_code,
            Supplier.deleted_at.is_(None),
            Supplier.is_active.is_(True),
        )
        .order_by(SupplierPrice.unit_price, SupplierPriceList.received_at.desc(), SupplierPrice.id)
    ).all()
    comparable = [
        (price, price_list, supplier)
        for price, price_list, supplier in rows
        if price.unit == product.unit
    ]
    excluded_units = sorted(
        {price.unit or "unknown" for price, _, _ in rows if price.unit != product.unit}
    )
    if not comparable:
        return {
            "data": {
                "product_id": product_id,
                "unit": product.unit,
                "lowest_price": None,
                "currency": context.tenant.currency_code,
                "excluded_units": excluded_units,
            }
        }
    price, price_list, supplier = comparable[0]
    return {
        "data": {
            "product_id": product_id,
            "unit": product.unit,
            "lowest_price": {
                "supplier_id": supplier.id,
                "supplier_name": supplier.name,
                "price_list_id": price_list.id,
                "received_at": price_list.received_at,
                "unit_price": price.unit_price,
                "currency": price.currency,
            },
            "excluded_units": excluded_units,
        }
    }
