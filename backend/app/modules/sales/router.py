"""Tenant-scoped sales order API."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import date
from decimal import Decimal, localcontext
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.modules.audit.models import IdempotencyKey
from app.modules.catalog.models import Product, ProductVariant
from app.modules.catalog.service import add_audit, lock_tenant
from app.modules.pricing.service import calculate_order
from app.modules.sales.allocation import allocate_order_discount, post_line_discount_basis
from app.modules.sales.models import (
    SaleItem,
    SalesOrder,
    SalesRefund,
    SalesReturn,
    SalesReturnItem,
)
from app.modules.tenancy.dependencies import TenantContext, require_permission

router = APIRouter(prefix="/sales", tags=["sales"])


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SaleLineInput(InputModel):
    product_id: int | None = Field(default=None, gt=0)
    variant_id: int | None = Field(default=None, gt=0)
    sku: str | None = Field(default=None, min_length=1, max_length=100)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    quantity: Decimal = Field(gt=0, max_digits=12, decimal_places=3)
    unit_price: Decimal = Field(ge=0, max_digits=20, decimal_places=2)
    line_discount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=20, decimal_places=2)

    @model_validator(mode="after")
    def validate_product_reference(self) -> SaleLineInput:
        if self.variant_id is not None and self.product_id is None:
            raise ValueError("variant_id requires product_id")
        if self.product_id is not None and (self.sku is not None or self.name is not None):
            raise ValueError("sku and name are derived from the selected product")
        if self.product_id is None and (not self.sku or not self.name):
            raise ValueError("manual sale lines require sku and name")
        if self.sku is not None and not self.sku.strip():
            raise ValueError("sku cannot be blank")
        if self.name is not None and not self.name.strip():
            raise ValueError("name cannot be blank")
        return self


class SalesOrderUpdate(InputModel):
    order_date: date | None = None
    channel: str | None = Field(default=None, max_length=80)
    customer_name: str | None = Field(default=None, max_length=200)
    notes: str | None = None
    payment_status: Literal["unpaid", "paid"] | None = None
    shipping_status: Literal["not_shipped", "shipped", "delivered"] | None = None


class SalesOrderTransition(InputModel):
    to: Literal["confirmed", "processing", "completed", "cancelled"]


class SalesReturnLineInput(InputModel):
    sale_item_id: int = Field(gt=0)
    quantity: Decimal = Field(gt=0, max_digits=12, decimal_places=3)
    refund_amount: Decimal = Field(ge=0, max_digits=20, decimal_places=2)


class SalesRefundCreate(InputModel):
    amount: Decimal = Field(gt=0, max_digits=20, decimal_places=2)
    notes: str | None = None

    @model_validator(mode="after")
    def clean_notes(self) -> SalesRefundCreate:
        if self.notes is not None:
            self.notes = self.notes.strip() or None
        return self


class SalesReturnCreate(InputModel):
    items: list[SalesReturnLineInput] = Field(min_length=1, max_length=500)
    notes: str | None = None

    @model_validator(mode="after")
    def unique_sale_items(self) -> SalesReturnCreate:
        ids = [item.sale_item_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("sale_item_id values must be unique")
        if self.notes is not None:
            self.notes = self.notes.strip() or None
        return self


class SaleItemUpdate(InputModel):
    quantity: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=3)
    unit_price: Decimal | None = Field(default=None, ge=0, max_digits=20, decimal_places=2)
    line_discount: Decimal | None = Field(default=None, ge=0, max_digits=20, decimal_places=2)


class SalesOrderCreate(InputModel):
    order_number: str = Field(min_length=1, max_length=100)
    order_date: date
    currency: Literal["IRT", "IRR"]
    items: list[SaleLineInput] = Field(min_length=1, max_length=500)
    order_discount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=20, decimal_places=2)
    channel: str | None = Field(default=None, max_length=80)
    customer_name: str | None = Field(default=None, max_length=200)
    notes: str | None = None

    @model_validator(mode="after")
    def clean_strings(self) -> SalesOrderCreate:
        self.order_number = self.order_number.strip()
        if not self.order_number:
            raise ValueError("order_number cannot be blank")
        if self.channel is not None:
            self.channel = self.channel.strip() or None
        if self.customer_name is not None:
            self.customer_name = self.customer_name.strip() or None
        return self


def _validate_idempotency_key(value: str | None) -> str:
    if value is None or not value.strip() or len(value) > 255 or any(ord(c) < 32 for c in value):
        raise HTTPException(status_code=422, detail="IDEMPOTENCY_KEY_REQUIRED")
    return value


def _reserve_idempotency(
    context: TenantContext, *, key: str, operation: str, request_hash: str
) -> tuple[int, JSONResponse | None]:
    db = context.auth.db
    settings = get_settings()
    statement = pg_insert(IdempotencyKey).values(
        tenant_id=context.tenant.id,
        user_id=context.auth.user.id,
        idempotency_key=key,
        operation=operation,
        request_hash=request_hash,
        response_status=None,
        response_body=None,
        created_at=func.clock_timestamp(),
        expires_at=func.clock_timestamp()
        + func.make_interval(0, 0, 0, 0, settings.idempotency_ttl_hours, 0, 0),
    )
    reserved_id = db.scalar(
        statement.on_conflict_do_update(
            index_elements=[
                IdempotencyKey.tenant_id,
                IdempotencyKey.user_id,
                IdempotencyKey.idempotency_key,
            ],
            set_={
                "operation": statement.excluded.operation,
                "request_hash": statement.excluded.request_hash,
                "response_status": None,
                "response_body": None,
                "created_at": func.clock_timestamp(),
                "expires_at": func.clock_timestamp()
                + func.make_interval(0, 0, 0, 0, settings.idempotency_ttl_hours, 0, 0),
            },
            where=IdempotencyKey.expires_at <= func.clock_timestamp(),
        ).returning(IdempotencyKey.id)
    )
    if reserved_id is not None:
        return reserved_id, None
    idem = db.scalar(
        select(IdempotencyKey)
        .where(
            IdempotencyKey.tenant_id == context.tenant.id,
            IdempotencyKey.user_id == context.auth.user.id,
            IdempotencyKey.idempotency_key == key,
        )
        .with_for_update()
    )
    if idem is None:
        db.rollback()
        raise HTTPException(status_code=409, detail="IDEMPOTENCY_CONFLICT")
    if idem.operation != operation or idem.request_hash != request_hash:
        db.rollback()
        raise HTTPException(status_code=409, detail="IDEMPOTENCY_CONFLICT")
    if idem.response_status is not None and idem.response_body is not None:
        replay = JSONResponse(status_code=idem.response_status, content=idem.response_body)
        db.commit()
        return idem.id, replay
    db.rollback()
    raise HTTPException(status_code=409, detail="IDEMPOTENCY_IN_PROGRESS")


def _item_data(item: SaleItem) -> dict[str, Any]:
    with localcontext() as decimal_context:
        decimal_context.prec = 60
        gross = item.quantity * item.unit_price
        net = gross - item.line_discount - item.order_discount_share
    return {
        "id": item.id,
        "product_id": item.product_id,
        "variant_id": item.variant_id,
        "sku": item.sku_snapshot,
        "name": item.name_snapshot,
        "quantity": str(item.quantity),
        "unit_price": str(item.unit_price),
        "line_discount": str(item.line_discount),
        "order_discount_share": str(item.order_discount_share),
        "unit_cost": str(item.unit_cost) if item.unit_cost is not None else None,
        "cost_source": item.cost_source,
        "gross_amount": str(gross),
        "net_amount": str(net),
        "returned_quantity": str(item.returned_quantity),
        "refund_amount": str(item.refund_amount),
    }


def _order_data(order: SalesOrder, items: list[SaleItem] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "id": order.id,
        "order_number": order.order_number,
        "order_date": order.order_date.isoformat(),
        "channel": order.channel,
        "status": order.status,
        "payment_status": order.payment_status,
        "shipping_status": order.shipping_status,
        "currency": order.currency,
        "order_discount": str(order.order_discount),
        "customer_name": order.customer_name,
        "notes": order.notes,
        "created_at": order.created_at.isoformat(),
        "updated_at": order.updated_at.isoformat(),
    }
    if items is not None:
        result["items"] = [_item_data(item) for item in items]
        with localcontext() as decimal_context:
            decimal_context.prec = 60
            gross_total = sum((i.quantity * i.unit_price for i in items), Decimal("0"))
            line_discount_total = sum((i.line_discount for i in items), Decimal("0"))
            order_discount_total = sum((i.order_discount_share for i in items), Decimal("0"))
            net_total = sum(
                (
                    i.quantity * i.unit_price - i.line_discount - i.order_discount_share
                    for i in items
                ),
                Decimal("0"),
            )
        result["gross_total"] = str(gross_total)
        result["line_discount_total"] = str(line_discount_total)
        result["order_discount_total"] = str(order_discount_total)
        result["net_total"] = str(net_total)
    return result


@router.post("/orders", status_code=status.HTTP_201_CREATED)
def create_sales_order(
    payload: SalesOrderCreate,
    request: Request,
    context: TenantContext = Depends(require_permission("sales:write")),
) -> dict[str, Any]:
    db, tenant_id = context.auth.db, context.tenant.id
    tenant = lock_tenant(db, tenant_id)
    if payload.currency != tenant.currency_code:
        raise HTTPException(status_code=422, detail="CURRENCY_MISMATCH")

    line_bases: list[Decimal] = []
    resolved: list[tuple[SaleLineInput, str, str, Decimal | None, str, int | None, int | None]] = []
    for line in payload.items:
        try:
            basis = post_line_discount_basis(line.quantity, line.unit_price, line.line_discount)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="INVALID_LINE_DISCOUNT") from exc
        line_bases.append(basis)
        if line.product_id is None:
            resolved.append(
                (line, str(line.sku).strip(), str(line.name).strip(), None, "unknown", None, None)
            )
            continue
        product = db.scalar(
            select(Product)
            .where(
                Product.id == line.product_id,
                Product.tenant_id == tenant_id,
                Product.deleted_at.is_(None),
                Product.is_active.is_(True),
            )
            .with_for_update()
        )
        if product is None:
            raise HTTPException(status_code=404, detail="NOT_FOUND")
        sku, variant_id = product.sku, None
        if line.variant_id is not None:
            variant = db.scalar(
                select(ProductVariant)
                .where(
                    ProductVariant.id == line.variant_id,
                    ProductVariant.tenant_id == tenant_id,
                    ProductVariant.product_id == product.id,
                    ProductVariant.deleted_at.is_(None),
                    ProductVariant.is_active.is_(True),
                )
                .with_for_update()
            )
            if variant is None:
                raise HTTPException(status_code=404, detail="NOT_FOUND")
            sku, variant_id = variant.sku, variant.id
        resolved.append(
            (
                line,
                sku,
                product.name,
                product.purchase_cost,
                "product_current" if product.purchase_cost is not None else "unknown",
                product.id,
                variant_id,
            )
        )

    try:
        shares = allocate_order_discount(line_bases, payload.order_discount, Decimal("1"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="INVALID_ORDER_DISCOUNT") from exc

    order = SalesOrder(
        tenant_id=tenant_id,
        order_number=payload.order_number,
        order_date=payload.order_date,
        channel=payload.channel,
        currency=payload.currency,
        order_discount=payload.order_discount,
        customer_name=payload.customer_name,
        notes=payload.notes,
        created_by=context.auth.user.id,
    )
    db.add(order)
    try:
        db.flush()
        for (line, sku, name, unit_cost, cost_source, product_id, variant_id), share in zip(
            resolved, shares, strict=True
        ):
            db.add(
                SaleItem(
                    tenant_id=tenant_id,
                    order_id=order.id,
                    product_id=product_id,
                    variant_id=variant_id,
                    sku_snapshot=sku,
                    name_snapshot=name,
                    quantity=line.quantity,
                    unit_price=line.unit_price,
                    line_discount=line.line_discount,
                    order_discount_share=share,
                    unit_cost=unit_cost,
                    cost_source=cost_source,
                )
            )
        add_audit(
            db,
            request,
            user_id=context.auth.user.id,
            tenant_id=tenant_id,
            action="sales.order_created",
            entity_type="sales_order",
            entity_id=order.id,
            detail={"item_count": len(payload.items), "currency": payload.currency},
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="RESOURCE_CONFLICT") from exc
    items = db.scalars(
        select(SaleItem)
        .where(SaleItem.tenant_id == tenant_id, SaleItem.order_id == order.id)
        .order_by(SaleItem.id)
    ).all()
    return {"data": _order_data(order, list(items))}


def _lock_mutable_order_items(
    context: TenantContext, order_id: int
) -> tuple[SalesOrder, list[SaleItem]]:
    db, tenant_id = context.auth.db, context.tenant.id
    order = db.scalar(
        select(SalesOrder)
        .where(SalesOrder.id == order_id, SalesOrder.tenant_id == tenant_id)
        .with_for_update()
    )
    if order is None:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    if order.status in {"completed", "cancelled"}:
        raise HTTPException(status_code=409, detail="ORDER_IMMUTABLE")
    if order.payment_status != "unpaid":
        raise HTTPException(status_code=409, detail="PAID_ORDER_IMMUTABLE")
    has_returns = db.scalar(
        select(SalesReturn.id)
        .where(SalesReturn.tenant_id == tenant_id, SalesReturn.order_id == order_id)
        .limit(1)
    )
    if has_returns is not None:
        raise HTTPException(status_code=409, detail="ORDER_HAS_RETURNS")
    items = db.scalars(
        select(SaleItem)
        .where(SaleItem.tenant_id == tenant_id, SaleItem.order_id == order_id)
        .order_by(SaleItem.id)
        .with_for_update()
    ).all()
    return order, list(items)


def _reallocate_order_discount(items: list[SaleItem], order_discount: Decimal) -> None:
    try:
        bases = [
            post_line_discount_basis(item.quantity, item.unit_price, item.line_discount)
            for item in items
        ]
        shares = allocate_order_discount(bases, order_discount, Decimal("1"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="INVALID_ORDER_DISCOUNT") from exc
    for item, share in zip(items, shares, strict=True):
        item.order_discount_share = share


def _resolve_sale_line(
    context: TenantContext, line: SaleLineInput
) -> tuple[str, str, Decimal | None, str, int | None, int | None]:
    if line.product_id is None:
        return str(line.sku).strip(), str(line.name).strip(), None, "unknown", None, None
    db, tenant_id = context.auth.db, context.tenant.id
    product = db.scalar(
        select(Product)
        .where(
            Product.id == line.product_id,
            Product.tenant_id == tenant_id,
            Product.deleted_at.is_(None),
            Product.is_active.is_(True),
        )
        .with_for_update()
    )
    if product is None:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    sku, variant_id = product.sku, None
    if line.variant_id is not None:
        variant = db.scalar(
            select(ProductVariant)
            .where(
                ProductVariant.id == line.variant_id,
                ProductVariant.tenant_id == tenant_id,
                ProductVariant.product_id == product.id,
                ProductVariant.deleted_at.is_(None),
                ProductVariant.is_active.is_(True),
            )
            .with_for_update()
        )
        if variant is None:
            raise HTTPException(status_code=404, detail="NOT_FOUND")
        sku, variant_id = variant.sku, variant.id
    cost_source = "product_current" if product.purchase_cost is not None else "unknown"
    return sku, product.name, product.purchase_cost, cost_source, product.id, variant_id


@router.post("/orders/{order_id}/items", status_code=status.HTTP_201_CREATED)
def add_sales_order_item(
    order_id: int,
    payload: SaleLineInput,
    request: Request,
    context: TenantContext = Depends(require_permission("sales:write")),
) -> dict[str, Any]:
    db, tenant_id = context.auth.db, context.tenant.id
    lock_tenant(db, tenant_id)
    order, items = _lock_mutable_order_items(context, order_id)
    try:
        post_line_discount_basis(payload.quantity, payload.unit_price, payload.line_discount)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="INVALID_LINE_DISCOUNT") from exc
    sku, name, unit_cost, cost_source, product_id, variant_id = _resolve_sale_line(context, payload)
    item = SaleItem(
        tenant_id=tenant_id,
        order_id=order.id,
        product_id=product_id,
        variant_id=variant_id,
        sku_snapshot=sku,
        name_snapshot=name,
        quantity=payload.quantity,
        unit_price=payload.unit_price,
        line_discount=payload.line_discount,
        unit_cost=unit_cost,
        cost_source=cost_source,
    )
    db.add(item)
    db.flush()
    items.append(item)
    _reallocate_order_discount(items, order.order_discount)
    add_audit(
        db,
        request,
        user_id=context.auth.user.id,
        tenant_id=tenant_id,
        action="sales.order_item_added",
        entity_type="sales_order",
        entity_id=order.id,
        detail={"sale_item_id": item.id},
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="RESOURCE_CONFLICT") from exc
    return {"data": _item_data(item)}


@router.patch("/orders/{order_id}/items/{item_id}")
def update_sales_order_item(
    order_id: int,
    item_id: int,
    payload: SaleItemUpdate,
    request: Request,
    context: TenantContext = Depends(require_permission("sales:write")),
) -> dict[str, Any]:
    db, tenant_id = context.auth.db, context.tenant.id
    lock_tenant(db, tenant_id)
    order, items = _lock_mutable_order_items(context, order_id)
    item = next((row for row in items if row.id == item_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    changes = payload.model_dump(exclude_unset=True)
    if not changes or any(value is None for value in changes.values()):
        raise HTTPException(status_code=422, detail="REQUEST_INVALID")
    candidate = {
        "quantity": changes.get("quantity", item.quantity),
        "unit_price": changes.get("unit_price", item.unit_price),
        "line_discount": changes.get("line_discount", item.line_discount),
    }
    try:
        post_line_discount_basis(**candidate)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="INVALID_LINE_DISCOUNT") from exc
    for field, value in candidate.items():
        setattr(item, field, value)
    _reallocate_order_discount(items, order.order_discount)
    add_audit(
        db,
        request,
        user_id=context.auth.user.id,
        tenant_id=tenant_id,
        action="sales.order_item_updated",
        entity_type="sales_order",
        entity_id=order.id,
        detail={"sale_item_id": item.id, "fields": sorted(changes)},
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="RESOURCE_CONFLICT") from exc
    return {"data": _item_data(item)}


@router.delete("/orders/{order_id}/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_sales_order_item(
    order_id: int,
    item_id: int,
    request: Request,
    context: TenantContext = Depends(require_permission("sales:write")),
) -> Response:
    db, tenant_id = context.auth.db, context.tenant.id
    lock_tenant(db, tenant_id)
    order, items = _lock_mutable_order_items(context, order_id)
    item = next((row for row in items if row.id == item_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    remaining = [row for row in items if row.id != item_id]
    if not remaining:
        raise HTTPException(status_code=409, detail="ORDER_MUST_HAVE_ITEMS")
    _reallocate_order_discount(remaining, order.order_discount)
    db.delete(item)
    add_audit(
        db,
        request,
        user_id=context.auth.user.id,
        tenant_id=tenant_id,
        action="sales.order_item_deleted",
        entity_type="sales_order",
        entity_id=order.id,
        detail={"sale_item_id": item.id},
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="RESOURCE_CONFLICT") from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/orders/{order_id}")
def update_sales_order(
    order_id: int,
    payload: SalesOrderUpdate,
    request: Request,
    context: TenantContext = Depends(require_permission("sales:write")),
) -> dict[str, Any]:
    db, tenant_id = context.auth.db, context.tenant.id
    lock_tenant(db, tenant_id)
    order = db.scalar(
        select(SalesOrder)
        .where(SalesOrder.id == order_id, SalesOrder.tenant_id == tenant_id)
        .with_for_update()
    )
    if order is None:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    if order.status in {"completed", "cancelled"}:
        raise HTTPException(status_code=409, detail="ORDER_IMMUTABLE")
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="REQUEST_INVALID")
    if any(
        changes.get(field) is None
        for field in ("order_date", "payment_status", "shipping_status")
        if field in changes
    ):
        raise HTTPException(status_code=422, detail="REQUEST_INVALID")
    if (
        "payment_status" in changes
        and changes["payment_status"] != order.payment_status
        and not (order.payment_status == "unpaid" and changes["payment_status"] == "paid")
    ):
        raise HTTPException(status_code=409, detail="PAYMENT_STATE_INVALID")
    if "shipping_status" in changes and changes["shipping_status"] != order.shipping_status:
        allowed_shipping = {
            "not_shipped": {"shipped"},
            "shipped": {"delivered"},
            "delivered": set(),
        }
        if changes["shipping_status"] not in allowed_shipping.get(order.shipping_status, set()):
            raise HTTPException(status_code=409, detail="SHIPPING_STATE_INVALID")
    for field, value in changes.items():
        if field in {"channel", "customer_name", "notes"} and isinstance(value, str):
            value = value.strip() or None
        setattr(order, field, value)
    add_audit(
        db,
        request,
        user_id=context.auth.user.id,
        tenant_id=tenant_id,
        action="sales.order_updated",
        entity_type="sales_order",
        entity_id=order.id,
        detail={"fields": sorted(changes)},
    )
    db.commit()
    return {"data": _order_data(order)}


@router.post("/orders/{order_id}/status-transition")
def transition_sales_order(
    order_id: int,
    payload: SalesOrderTransition,
    request: Request,
    context: TenantContext = Depends(require_permission("sales:write")),
) -> dict[str, Any]:
    db, tenant_id = context.auth.db, context.tenant.id
    lock_tenant(db, tenant_id)
    order = db.scalar(
        select(SalesOrder)
        .where(SalesOrder.id == order_id, SalesOrder.tenant_id == tenant_id)
        .with_for_update()
    )
    if order is None:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    allowed = {
        "pending": {"confirmed", "cancelled"},
        "confirmed": {"processing", "cancelled"},
        "processing": {"completed", "cancelled"},
        "completed": set(),
        "cancelled": set(),
    }
    previous = order.status
    if payload.to not in allowed[previous]:
        raise HTTPException(
            status_code=409,
            detail={"code": "ORDER_STATE_INVALID", "from": previous, "to": payload.to},
        )
    if payload.to == "cancelled" and order.shipping_status != "not_shipped":
        raise HTTPException(status_code=409, detail="ORDER_ALREADY_SHIPPED_USE_RETURN")
    order.status = payload.to
    add_audit(
        db,
        request,
        user_id=context.auth.user.id,
        tenant_id=tenant_id,
        action="sales.order_status_transitioned",
        entity_type="sales_order",
        entity_id=order.id,
        detail={"from": previous, "to": payload.to},
    )
    db.commit()
    return {"data": _order_data(order)}


@router.get("/orders")
def list_sales_orders(
    status_filter: Literal["pending", "confirmed", "processing", "completed", "cancelled"]
    | None = Query(default=None, alias="status"),
    payment_status: Literal["unpaid", "paid", "refunded", "partially_refunded"] | None = None,
    channel: str | None = Query(default=None, max_length=80),
    query: str | None = Query(default=None, max_length=200),
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    context: TenantContext = Depends(require_permission("sales:read")),
) -> dict[str, Any]:
    db, tenant_id = context.auth.db, context.tenant.id
    base = select(SalesOrder).where(SalesOrder.tenant_id == tenant_id)
    if status_filter:
        base = base.where(SalesOrder.status == status_filter)
    if payment_status:
        base = base.where(SalesOrder.payment_status == payment_status)
    if channel and channel.strip():
        base = base.where(SalesOrder.channel == channel.strip())
    if query and query.strip():
        pattern = f"%{query.strip()}%"
        base = base.where(
            or_(SalesOrder.order_number.ilike(pattern), SalesOrder.customer_name.ilike(pattern))
        )
    if date_from:
        base = base.where(SalesOrder.order_date >= date_from)
    if date_to:
        base = base.where(SalesOrder.order_date <= date_to)
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=422, detail="INVALID_DATE_RANGE")
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(
        base.order_by(SalesOrder.order_date.desc(), SalesOrder.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "data": [_order_data(row) for row in rows],
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "pages": (total + page_size - 1) // page_size,
        },
    }


def _order_net_total(items: Sequence[SaleItem]) -> Decimal:
    with localcontext() as decimal_context:
        decimal_context.prec = 60
        return sum(
            (i.quantity * i.unit_price - i.line_discount - i.order_discount_share for i in items),
            Decimal("0"),
        )


def _refresh_order_refund_status(
    db: Any, order: SalesOrder, tenant_id: int, items: Sequence[SaleItem]
) -> Decimal:
    returned = db.scalar(
        select(func.coalesce(func.sum(SalesReturnItem.refund_amount), 0))
        .join(
            SaleItem,
            (SaleItem.id == SalesReturnItem.sale_item_id)
            & (SaleItem.tenant_id == SalesReturnItem.tenant_id),
        )
        .where(SaleItem.tenant_id == tenant_id, SaleItem.order_id == order.id)
    )
    independent = db.scalar(
        select(func.coalesce(func.sum(SalesRefund.amount), 0)).where(
            SalesRefund.tenant_id == tenant_id, SalesRefund.order_id == order.id
        )
    )
    with localcontext() as decimal_context:
        decimal_context.prec = 60
        cumulative = Decimal(returned or 0) + Decimal(independent or 0)
        received = _order_net_total(items)
    if cumulative > received:
        raise HTTPException(status_code=409, detail="REFUND_EXCEEDS_AMOUNT_RECEIVED")
    if cumulative > 0:
        order.payment_status = "refunded" if cumulative == received else "partially_refunded"
    else:
        order.payment_status = "paid"
    return cumulative


@router.post("/orders/{order_id}/returns", status_code=status.HTTP_201_CREATED)
def create_sales_return(
    order_id: int,
    payload: SalesReturnCreate,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    context: TenantContext = Depends(require_permission("sales:write")),
) -> JSONResponse:
    db, tenant_id = context.auth.db, context.tenant.id
    key = _validate_idempotency_key(idempotency_key)
    operation = f"sales.return.create:{order_id}"
    request_hash = hashlib.sha256(
        json.dumps(
            {"method": "POST", "path": request.url.path, "body": payload.model_dump(mode="json")},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    lock_tenant(db, tenant_id)
    idempotency_id, replay = _reserve_idempotency(
        context, key=key, operation=operation, request_hash=request_hash
    )
    if replay is not None:
        return replay

    order = db.scalar(
        select(SalesOrder)
        .where(SalesOrder.id == order_id, SalesOrder.tenant_id == tenant_id)
        .with_for_update()
    )
    if order is None:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    if order.status == "cancelled":
        raise HTTPException(status_code=409, detail="ORDER_CANCELLED")
    if order.payment_status == "unpaid":
        raise HTTPException(status_code=409, detail="ORDER_NOT_PAID")
    if order.shipping_status not in {"shipped", "delivered"}:
        raise HTTPException(status_code=409, detail="ORDER_NOT_SHIPPED")

    item_ids = [item.sale_item_id for item in payload.items]
    sale_items = db.scalars(
        select(SaleItem)
        .where(
            SaleItem.tenant_id == tenant_id,
            SaleItem.order_id == order.id,
            SaleItem.id.in_(item_ids),
        )
        .order_by(SaleItem.id)
        .with_for_update()
    ).all()
    if len(sale_items) != len(item_ids):
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    by_id = {item.id: item for item in sale_items}
    return_number = f"RET-{order.id}-{uuid4().hex[:12].upper()}"
    return_row = SalesReturn(
        tenant_id=tenant_id,
        return_number=return_number,
        order_id=order.id,
        return_date=date.today(),
        refund_metadata={"currency": order.currency},
        notes=payload.notes,
        created_by=context.auth.user.id,
    )
    db.add(return_row)
    try:
        db.flush()
        refund_total = Decimal("0")
        for requested in payload.items:
            sale_item = by_id[requested.sale_item_id]
            if sale_item.returned_quantity + requested.quantity > sale_item.quantity:
                raise HTTPException(status_code=409, detail="RETURN_QUANTITY_EXCEEDED")
            sale_item.returned_quantity += requested.quantity
            sale_item.refund_amount += requested.refund_amount
            refund_total += requested.refund_amount
            db.add(
                SalesReturnItem(
                    tenant_id=tenant_id,
                    return_id=return_row.id,
                    sale_item_id=sale_item.id,
                    quantity=requested.quantity,
                    refund_amount=requested.refund_amount,
                    sku_snapshot=sale_item.sku_snapshot,
                    name_snapshot=sale_item.name_snapshot,
                )
            )
        db.flush()
        all_items = db.scalars(
            select(SaleItem)
            .where(SaleItem.tenant_id == tenant_id, SaleItem.order_id == order.id)
            .order_by(SaleItem.id)
            .with_for_update()
        ).all()
        return_totals = db.execute(
            select(SalesReturnItem.sale_item_id, func.sum(SalesReturnItem.quantity))
            .join(
                SaleItem,
                (SaleItem.id == SalesReturnItem.sale_item_id)
                & (SaleItem.tenant_id == SalesReturnItem.tenant_id),
            )
            .where(SaleItem.tenant_id == tenant_id, SaleItem.order_id == order.id)
            .group_by(SalesReturnItem.sale_item_id)
        ).all()
        returned_by_item = {item_id: quantity for item_id, quantity in return_totals}
        cumulative_refund = _refresh_order_refund_status(db, order, tenant_id, all_items)
        fully_returned = all(
            returned_by_item.get(item.id, Decimal("0")) >= item.quantity for item in all_items
        )
        if fully_returned and order.shipping_status in {"shipped", "delivered"}:
            order.shipping_status = "returned"
        return_row.refund_metadata = {
            "currency": order.currency,
            "refund_total": str(refund_total),
            "cumulative_refund": str(cumulative_refund),
        }
        response_body = {
            "data": {
                "id": return_row.id,
                "return_number": return_row.return_number,
                "order_id": order.id,
                "return_date": return_row.return_date.isoformat(),
                "refund_total": str(refund_total),
                "currency": order.currency,
                "items": [
                    {
                        "sale_item_id": item.sale_item_id,
                        "quantity": str(item.quantity),
                        "refund_amount": str(item.refund_amount),
                        "sku": item.sku_snapshot,
                        "name": item.name_snapshot,
                    }
                    for item in db.scalars(
                        select(SalesReturnItem)
                        .where(
                            SalesReturnItem.tenant_id == tenant_id,
                            SalesReturnItem.return_id == return_row.id,
                        )
                        .order_by(SalesReturnItem.id)
                    ).all()
                ],
            }
        }
        idem = db.get(IdempotencyKey, idempotency_id)
        if idem is None:
            raise HTTPException(status_code=409, detail="IDEMPOTENCY_CONFLICT")
        idem.response_status = status.HTTP_201_CREATED
        idem.response_body = response_body
        add_audit(
            db,
            request,
            user_id=context.auth.user.id,
            tenant_id=tenant_id,
            action="sales.return_created",
            entity_type="sales_return",
            entity_id=return_row.id,
            detail={
                "order_id": order.id,
                "item_count": len(payload.items),
                "refund_total": str(refund_total),
            },
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="RESOURCE_CONFLICT") from exc
    return JSONResponse(status_code=status.HTTP_201_CREATED, content=response_body)


@router.post("/orders/{order_id}/refunds", status_code=status.HTTP_201_CREATED)
def create_sales_refund(
    order_id: int,
    payload: SalesRefundCreate,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    context: TenantContext = Depends(require_permission("sales:write")),
) -> JSONResponse:
    db, tenant_id = context.auth.db, context.tenant.id
    key = _validate_idempotency_key(idempotency_key)
    operation = f"sales.refund.create:{order_id}"
    request_hash = hashlib.sha256(
        json.dumps(
            {"method": "POST", "path": request.url.path, "body": payload.model_dump(mode="json")},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    lock_tenant(db, tenant_id)
    idempotency_id, replay = _reserve_idempotency(
        context, key=key, operation=operation, request_hash=request_hash
    )
    if replay is not None:
        return replay
    order = db.scalar(
        select(SalesOrder)
        .where(SalesOrder.id == order_id, SalesOrder.tenant_id == tenant_id)
        .with_for_update()
    )
    if order is None:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    if order.status != "cancelled":
        raise HTTPException(status_code=409, detail="INDEPENDENT_REFUND_REQUIRES_CANCELLED_ORDER")
    if order.payment_status == "unpaid":
        raise HTTPException(status_code=409, detail="ORDER_NOT_PAID")
    items = db.scalars(
        select(SaleItem)
        .where(SaleItem.tenant_id == tenant_id, SaleItem.order_id == order.id)
        .order_by(SaleItem.id)
        .with_for_update()
    ).all()
    prior_refunds = db.scalar(
        select(func.coalesce(func.sum(SalesRefund.amount), 0)).where(
            SalesRefund.tenant_id == tenant_id, SalesRefund.order_id == order.id
        )
    )
    return_refunds = db.scalar(
        select(func.coalesce(func.sum(SalesReturnItem.refund_amount), 0))
        .join(
            SaleItem,
            (SaleItem.id == SalesReturnItem.sale_item_id)
            & (SaleItem.tenant_id == SalesReturnItem.tenant_id),
        )
        .where(SaleItem.tenant_id == tenant_id, SaleItem.order_id == order.id)
    )
    with localcontext() as decimal_context:
        decimal_context.prec = 60
        already_refunded = Decimal(prior_refunds or 0) + Decimal(return_refunds or 0)
        total_received = _order_net_total(list(items))
        cumulative = already_refunded + payload.amount
    if cumulative > total_received:
        raise HTTPException(status_code=409, detail="REFUND_EXCEEDS_AMOUNT_RECEIVED")
    refund = SalesRefund(
        tenant_id=tenant_id,
        refund_number=f"RF-{order.id}-{uuid4().hex[:12].upper()}",
        order_id=order.id,
        refund_date=date.today(),
        amount=payload.amount,
        currency=order.currency,
        notes=payload.notes,
        created_by=context.auth.user.id,
    )
    db.add(refund)
    db.flush()
    order.payment_status = "refunded" if cumulative == total_received else "partially_refunded"
    response_body = {
        "data": {
            "id": refund.id,
            "refund_number": refund.refund_number,
            "order_id": order.id,
            "refund_date": refund.refund_date.isoformat(),
            "amount": str(refund.amount),
            "currency": refund.currency,
            "notes": refund.notes,
        }
    }
    idem = db.get(IdempotencyKey, idempotency_id)
    if idem is None:
        raise HTTPException(status_code=409, detail="IDEMPOTENCY_CONFLICT")
    idem.response_status, idem.response_body = status.HTTP_201_CREATED, response_body
    add_audit(
        db,
        request,
        user_id=context.auth.user.id,
        tenant_id=tenant_id,
        action="sales.refund_created",
        entity_type="sales_refund",
        entity_id=refund.id,
        detail={"order_id": order.id, "amount": str(refund.amount), "currency": refund.currency},
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="RESOURCE_CONFLICT") from exc
    return JSONResponse(status_code=status.HTTP_201_CREATED, content=response_body)


@router.get("/orders/{order_id}/refunds")
def list_sales_refunds(
    order_id: int,
    context: TenantContext = Depends(require_permission("sales:read")),
) -> dict[str, Any]:
    db, tenant_id = context.auth.db, context.tenant.id
    order = db.scalar(
        select(SalesOrder).where(SalesOrder.id == order_id, SalesOrder.tenant_id == tenant_id)
    )
    if order is None:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    refunds = db.scalars(
        select(SalesRefund)
        .where(SalesRefund.tenant_id == tenant_id, SalesRefund.order_id == order.id)
        .order_by(SalesRefund.refund_date.desc(), SalesRefund.id.desc())
    ).all()
    return {
        "data": [
            {
                "id": row.id,
                "refund_number": row.refund_number,
                "refund_date": row.refund_date.isoformat(),
                "amount": str(row.amount),
                "currency": row.currency,
                "notes": row.notes,
            }
            for row in refunds
        ]
    }


@router.get("/orders/{order_id}/returns")
def list_sales_returns(
    order_id: int,
    context: TenantContext = Depends(require_permission("sales:read")),
) -> dict[str, Any]:
    db, tenant_id = context.auth.db, context.tenant.id
    order = db.scalar(
        select(SalesOrder).where(SalesOrder.id == order_id, SalesOrder.tenant_id == tenant_id)
    )
    if order is None:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    returns = db.scalars(
        select(SalesReturn)
        .where(SalesReturn.tenant_id == tenant_id, SalesReturn.order_id == order.id)
        .order_by(SalesReturn.return_date.desc(), SalesReturn.id.desc())
    ).all()
    result = []
    for return_row in returns:
        items = db.scalars(
            select(SalesReturnItem)
            .where(
                SalesReturnItem.tenant_id == tenant_id,
                SalesReturnItem.return_id == return_row.id,
            )
            .order_by(SalesReturnItem.id)
        ).all()
        result.append(
            {
                "id": return_row.id,
                "return_number": return_row.return_number,
                "return_date": return_row.return_date.isoformat(),
                "refund_metadata": return_row.refund_metadata,
                "notes": return_row.notes,
                "items": [
                    {
                        "sale_item_id": item.sale_item_id,
                        "quantity": str(item.quantity),
                        "refund_amount": str(item.refund_amount),
                        "sku": item.sku_snapshot,
                        "name": item.name_snapshot,
                    }
                    for item in items
                ],
            }
        )
    return {"data": result}


@router.get("/orders/{order_id}")
def get_sales_order(
    order_id: int,
    context: TenantContext = Depends(require_permission("sales:read")),
) -> dict[str, Any]:
    db, tenant_id = context.auth.db, context.tenant.id
    order = db.scalar(
        select(SalesOrder).where(SalesOrder.id == order_id, SalesOrder.tenant_id == tenant_id)
    )
    if order is None:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    items = db.scalars(
        select(SaleItem)
        .where(SaleItem.tenant_id == tenant_id, SaleItem.order_id == order.id)
        .order_by(SaleItem.id)
    ).all()
    return {"data": _order_data(order, list(items))}


@router.get("/orders/{order_id}/profit")
def get_sales_order_profit(
    order_id: int,
    context: TenantContext = Depends(require_permission("pricing:read")),
) -> dict[str, Any]:
    try:
        result = calculate_order(
            context.auth.db,
            tenant_id=context.tenant.id,
            order_id=order_id,
            user_id=context.auth.user.id,
        )
    except LookupError as exc:
        context.auth.db.rollback()
        raise HTTPException(status_code=404, detail="NOT_FOUND") from exc
    except ValueError as exc:
        context.auth.db.rollback()
        detail = "CURRENCY_MISMATCH" if str(exc) == "CURRENCY_MISMATCH" else "CALCULATION_INVALID"
        raise HTTPException(status_code=422, detail=detail) from exc
    return {"data": result}
