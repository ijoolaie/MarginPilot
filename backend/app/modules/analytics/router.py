"""Tenant-scoped period analytics endpoints."""

from __future__ import annotations

from datetime import date
from io import BytesIO
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from openpyxl import Workbook  # type: ignore[import-untyped]
from openpyxl.styles import Font, PatternFill  # type: ignore[import-untyped]

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


@router.get("/export.xlsx")
def export_analytics(
    date_from: date,
    date_to: date,
    group_by: Literal["day", "month"] = "day",
    context: TenantContext = Depends(require_permission("analytics:read")),
) -> StreamingResponse:
    _validate(date_from, date_to)
    db, tenant_id, user_id = context.auth.db, context.tenant.id, context.auth.user.id
    summary = _run(service.summary, db, tenant_id, user_id, date_from, date_to)["data"]
    products = _run(service.products_report, db, tenant_id, user_id, date_from, date_to)["data"]
    trends = _run(service.trends_report, db, tenant_id, user_id, date_from, date_to, group_by)[
        "data"
    ]
    expenses = _run(service.expenses_report, db, tenant_id, user_id, date_from, date_to)["data"]

    workbook = Workbook()
    overview = workbook.active
    overview.title = "Summary"
    overview.append(["Metric", "Value", "Currency"])
    for key, label in (
        ("revenue", "Revenue"),
        ("gross_profit", "Gross profit"),
        ("net_profit", "Net operating profit"),
        ("cogs", "COGS"),
        ("expenses", "Expenses"),
        ("refunds", "Refunds"),
        ("margin_pct", "Profit margin (%)"),
        ("sales_count", "Completed orders"),
        ("units_sold", "Units sold"),
        ("returned_units", "Returned units"),
        ("unknown_cost_revenue", "Revenue with unknown cost"),
        ("unallocated_order_expenses", "Unallocated order expenses"),
        ("period_expenses", "Period expenses"),
        ("cancelled_order_expenses", "Cancelled order expenses"),
    ):
        value = summary.get(key)
        overview.append([label, None if value is None else str(value), summary["currency"]])
    overview.append(["Formula version", summary.get("formula_version"), None])
    overview.append(["Data through", summary.get("data_through"), None])

    product_sheet = workbook.create_sheet("Products")
    product_sheet.append(
        [
            "Product ID",
            "SKU",
            "Product",
            "Revenue",
            "Gross profit",
            "Net profit",
            "Margin (%)",
            "Units sold",
            "Returned units",
            "Currency",
            "Warnings",
        ]
    )
    for item in products["products"]:
        product_sheet.append(
            [
                item.get("product_id"),
                item.get("sku"),
                item.get("name"),
                str(item.get("revenue")),
                str(item.get("gross_profit")) if item.get("gross_profit") is not None else None,
                str(item.get("net_profit")) if item.get("net_profit") is not None else None,
                str(item.get("margin_pct")) if item.get("margin_pct") is not None else None,
                str(item.get("units_sold")),
                str(item.get("returned_units")),
                item.get("currency"),
                ", ".join(item.get("warnings", [])),
            ]
        )

    trend_sheet = workbook.create_sheet("Trends")
    trend_sheet.append(
        ["Period", "Revenue", "Refunds", "COGS", "Expenses", "Gross profit", "Currency"]
    )
    for item in trends["items"]:
        trend_sheet.append(
            [
                item["period"],
                str(item["revenue"]),
                str(item["refunds"]),
                str(item["cogs"]),
                str(item["expenses"]),
                str(item["gross_profit"]) if item["gross_profit"] is not None else None,
                trends["currency"],
            ]
        )

    expense_sheet = workbook.create_sheet("Expenses")
    expense_sheet.append(["Type", "Scope", "Amount", "Currency"])
    for item in expenses["items"]:
        expense_sheet.append([item["type"], item["scope"], str(item["amount"]), item["currency"]])
    expense_sheet.append(
        [
            "Total included in period profit",
            None,
            str(expenses["total_in_period_profit"]),
            expenses["currency"],
        ]
    )
    expense_sheet.append(
        [
            "Product-scoped expenses excluded from period profit",
            None,
            str(expenses["product_scoped_excluded"]),
            expenses["currency"],
        ]
    )

    warning_sheet = workbook.create_sheet("Warnings")
    warning_sheet.append(["Source", "Warning code"])
    for source, report in (
        ("Summary", summary),
        ("Products", products),
        ("Trends", trends),
        ("Expenses", expenses),
    ):
        for warning in report.get("warnings", []):
            warning_sheet.append([source, warning])
    for sheet in workbook.worksheets:
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for row in sheet.iter_rows():
            for cell in row:
                if isinstance(cell.value, str) and cell.value.startswith("="):
                    cell.data_type = "s"
        for cell in sheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill(fill_type="solid", fgColor="0F766E")
        for column in sheet.columns:
            letter = column[0].column_letter
            width = min(max(max(len(str(cell.value or "")) for cell in column) + 2, 12), 48)
            sheet.column_dimensions[letter].width = width
    output = BytesIO()
    workbook.save(output)
    output.seek(0)
    filename = f"marginpilot-analytics-{date_from.isoformat()}-{date_to.isoformat()}.xlsx"
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
