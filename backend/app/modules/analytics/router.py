"""Tenant-scoped period analytics endpoints."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException

from app.modules.analytics import service
from app.modules.tenancy.dependencies import TenantContext, require_permission

router = APIRouter(prefix="/analytics", tags=["analytics"])


def _run(fn: Any, *args: Any) -> dict[str, Any]:
    try:
        return {"data": fn(*args)}
    except ValueError as exc:
        code = str(exc)
        status = 422 if code in {"INVALID_DATE_RANGE", "DATE_RANGE_TOO_LARGE"} else 409
        raise HTTPException(status_code=status, detail=code) from exc


def _validate(start: date, end: date) -> None:
    if start > end:
        raise HTTPException(status_code=422, detail="INVALID_DATE_RANGE")
    if (end - start).days > 365:
        raise HTTPException(status_code=422, detail="DATE_RANGE_TOO_LARGE")


@router.get("/summary")
def get_summary(
    date_from: date,
    date_to: date,
    context: TenantContext = Depends(require_permission("analytics:read")),
) -> dict[str, Any]:
    _validate(date_from, date_to)
    return _run(
        service.summary,
        context.auth.db,
        context.tenant.id,
        context.auth.user.id,
        date_from,
        date_to,
    )


@router.get("/products")
def get_products(
    date_from: date,
    date_to: date,
    context: TenantContext = Depends(require_permission("analytics:read")),
) -> dict[str, Any]:
    _validate(date_from, date_to)
    return _run(
        service.products_report,
        context.auth.db,
        context.tenant.id,
        context.auth.user.id,
        date_from,
        date_to,
    )


@router.get("/trends")
def get_trends(
    date_from: date,
    date_to: date,
    group_by: Literal["day", "month"] = "day",
    context: TenantContext = Depends(require_permission("analytics:read")),
) -> dict[str, Any]:
    _validate(date_from, date_to)
    return _run(
        service.trends_report,
        context.auth.db,
        context.tenant.id,
        context.auth.user.id,
        date_from,
        date_to,
        group_by,
    )


@router.get("/expenses")
def get_expenses(
    date_from: date,
    date_to: date,
    context: TenantContext = Depends(require_permission("analytics:read")),
) -> dict[str, Any]:
    _validate(date_from, date_to)
    return _run(
        service.expenses_report,
        context.auth.db,
        context.tenant.id,
        context.auth.user.id,
        date_from,
        date_to,
    )
