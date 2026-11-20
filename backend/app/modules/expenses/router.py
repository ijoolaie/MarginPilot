"""Tenant-scoped expense API."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.modules.catalog.models import Product
from app.modules.catalog.service import add_audit, lock_tenant
from app.modules.expenses.models import Expense
from app.modules.sales.models import SalesOrder
from app.modules.tenancy.dependencies import TenantContext, require_permission

router = APIRouter(prefix="/expenses", tags=["expenses"])

ExpenseType = Literal["shipping", "packaging", "advertising", "payment_fee", "operational", "other"]
AllocationScope = Literal["order", "product", "period"]
AllocationStrategy = Literal["revenue_share", "equal_quantity", "equal_count"]


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExpenseFields(InputModel):
    expense_date: date
    type: ExpenseType
    amount: Decimal = Field(gt=0, max_digits=20, decimal_places=2)
    currency: Literal["IRT", "IRR"]
    description: str | None = None
    allocation_scope: AllocationScope
    order_id: int | None = Field(default=None, gt=0)
    product_id: int | None = Field(default=None, gt=0)
    period_start: date | None = None
    period_end: date | None = None
    allocation_strategy: AllocationStrategy | None = None

    @model_validator(mode="after")
    def validate_scope_fields(self) -> ExpenseFields:
        if self.allocation_scope == "order":
            valid = (
                self.order_id is not None
                and self.product_id is None
                and self.period_start is None
                and self.period_end is None
            )
        elif self.allocation_scope == "product":
            valid = (
                self.product_id is not None
                and self.order_id is None
                and self.period_start is None
                and self.period_end is None
            )
        else:
            valid = (
                self.order_id is None
                and self.product_id is None
                and self.period_start is not None
                and self.period_end is not None
                and self.period_start <= self.period_end
            )
        if not valid:
            raise ValueError("allocation fields do not match allocation_scope")
        if self.description is not None:
            self.description = self.description.strip() or None
        return self


class ExpenseCreate(ExpenseFields):
    pass


class ExpenseUpdate(InputModel):
    expense_date: date | None = None
    type: ExpenseType | None = None
    amount: Decimal | None = Field(default=None, gt=0, max_digits=20, decimal_places=2)
    description: str | None = None
    allocation_scope: AllocationScope | None = None
    order_id: int | None = Field(default=None, gt=0)
    product_id: int | None = Field(default=None, gt=0)
    period_start: date | None = None
    period_end: date | None = None
    allocation_strategy: AllocationStrategy | None = None


def _expense_data(row: Expense) -> dict[str, Any]:
    return {
        "id": row.id,
        "expense_date": row.expense_date.isoformat(),
        "type": row.type,
        "amount": str(row.amount),
        "currency": row.currency,
        "description": row.description,
        "allocation_scope": row.allocation_scope,
        "order_id": row.order_id,
        "product_id": row.product_id,
        "period_start": row.period_start.isoformat() if row.period_start else None,
        "period_end": row.period_end.isoformat() if row.period_end else None,
        "allocation_strategy": row.allocation_strategy,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def _validate_targets(context: TenantContext, values: dict[str, Any]) -> None:
    db, tenant_id = context.auth.db, context.tenant.id
    if values["currency"] != context.tenant.currency_code:
        raise HTTPException(status_code=422, detail="CURRENCY_MISMATCH")
    if values["allocation_scope"] == "order":
        order = db.scalar(
            select(SalesOrder).where(
                SalesOrder.id == values["order_id"], SalesOrder.tenant_id == tenant_id
            )
        )
        if order is None:
            raise HTTPException(status_code=404, detail="NOT_FOUND")
        if order.currency != values["currency"]:
            raise HTTPException(status_code=422, detail="CURRENCY_MISMATCH")
    elif values["allocation_scope"] == "product":
        product = db.scalar(
            select(Product).where(
                Product.id == values["product_id"],
                Product.tenant_id == tenant_id,
                Product.deleted_at.is_(None),
            )
        )
        if product is None:
            raise HTTPException(status_code=404, detail="NOT_FOUND")


def _validate_scope(values: dict[str, Any]) -> None:
    scope = values.get("allocation_scope")
    if scope == "order":
        valid = (
            values.get("order_id") is not None
            and values.get("product_id") is None
            and values.get("period_start") is None
            and values.get("period_end") is None
        )
    elif scope == "product":
        valid = (
            values.get("product_id") is not None
            and values.get("order_id") is None
            and values.get("period_start") is None
            and values.get("period_end") is None
        )
    elif scope == "period":
        start, end = values.get("period_start"), values.get("period_end")
        valid = (
            values.get("order_id") is None
            and values.get("product_id") is None
            and start is not None
            and end is not None
            and start <= end
        )
    else:
        valid = False
    if not valid:
        raise HTTPException(status_code=422, detail="INVALID_ALLOCATION_SCOPE")


@router.post("", status_code=status.HTTP_201_CREATED)
def create_expense(
    payload: ExpenseCreate,
    request: Request,
    context: TenantContext = Depends(require_permission("expense:write")),
) -> dict[str, Any]:
    db, tenant_id = context.auth.db, context.tenant.id
    lock_tenant(db, tenant_id)
    values = payload.model_dump()
    _validate_targets(context, values)
    row = Expense(tenant_id=tenant_id, created_by=context.auth.user.id, **values)
    db.add(row)
    try:
        db.flush()
        add_audit(
            db,
            request,
            user_id=context.auth.user.id,
            tenant_id=tenant_id,
            action="expense.created",
            entity_type="expense",
            entity_id=row.id,
            detail={"allocation_scope": row.allocation_scope, "type": row.type},
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="RESOURCE_CONFLICT") from exc
    return {"data": _expense_data(row)}


@router.get("")
def list_expenses(
    expense_type: ExpenseType | None = Query(default=None, alias="type"),
    allocation_scope: AllocationScope | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    context: TenantContext = Depends(require_permission("expense:read")),
) -> dict[str, Any]:
    db, tenant_id = context.auth.db, context.tenant.id
    base = select(Expense).where(Expense.tenant_id == tenant_id, Expense.deleted_at.is_(None))
    if expense_type:
        base = base.where(Expense.type == expense_type)
    if allocation_scope:
        base = base.where(Expense.allocation_scope == allocation_scope)
    if date_from:
        base = base.where(Expense.expense_date >= date_from)
    if date_to:
        base = base.where(Expense.expense_date <= date_to)
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=422, detail="INVALID_DATE_RANGE")
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(
        base.order_by(Expense.expense_date.desc(), Expense.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "data": [_expense_data(row) for row in rows],
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "pages": (total + page_size - 1) // page_size,
        },
    }


@router.get("/{expense_id}")
def get_expense(
    expense_id: int,
    context: TenantContext = Depends(require_permission("expense:read")),
) -> dict[str, Any]:
    row = context.auth.db.scalar(
        select(Expense).where(
            Expense.id == expense_id,
            Expense.tenant_id == context.tenant.id,
            Expense.deleted_at.is_(None),
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    return {"data": _expense_data(row)}


@router.patch("/{expense_id}")
def update_expense(
    expense_id: int,
    payload: ExpenseUpdate,
    request: Request,
    context: TenantContext = Depends(require_permission("expense:write")),
) -> dict[str, Any]:
    db, tenant_id = context.auth.db, context.tenant.id
    lock_tenant(db, tenant_id)
    row = db.scalar(
        select(Expense)
        .where(
            Expense.id == expense_id, Expense.tenant_id == tenant_id, Expense.deleted_at.is_(None)
        )
        .with_for_update()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="REQUEST_INVALID")
    if any(
        changes.get(field) is None
        for field in ("expense_date", "type", "amount", "allocation_scope")
        if field in changes
    ):
        raise HTTPException(status_code=422, detail="REQUEST_INVALID")
    values = {
        field: getattr(row, field)
        for field in (
            "expense_date",
            "type",
            "amount",
            "currency",
            "description",
            "allocation_scope",
            "order_id",
            "product_id",
            "period_start",
            "period_end",
            "allocation_strategy",
        )
    }
    values.update(changes)
    _validate_scope(values)
    _validate_targets(context, values)
    for field, value in changes.items():
        setattr(
            row,
            field,
            value.strip() or None if field == "description" and value is not None else value,
        )
    add_audit(
        db,
        request,
        user_id=context.auth.user.id,
        tenant_id=tenant_id,
        action="expense.updated",
        entity_type="expense",
        entity_id=row.id,
        detail={"fields": sorted(changes)},
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="RESOURCE_CONFLICT") from exc
    return {"data": _expense_data(row)}


@router.delete("/{expense_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_expense(
    expense_id: int,
    request: Request,
    context: TenantContext = Depends(require_permission("expense:write")),
) -> Response:
    db, tenant_id = context.auth.db, context.tenant.id
    lock_tenant(db, tenant_id)
    row = db.scalar(
        select(Expense)
        .where(
            Expense.id == expense_id, Expense.tenant_id == tenant_id, Expense.deleted_at.is_(None)
        )
        .with_for_update()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    row.deleted_at = datetime.now(UTC)
    add_audit(
        db,
        request,
        user_id=context.auth.user.id,
        tenant_id=tenant_id,
        action="expense.deleted",
        entity_type="expense",
        entity_id=row.id,
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
