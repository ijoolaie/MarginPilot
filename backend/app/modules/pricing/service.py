"""Tenant-scoped orchestration and immutable provenance for FV-2 calculations."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, localcontext
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.expenses.models import Expense
from app.modules.pricing.engine import (
    FORMULA_VERSION,
    SaleLine,
    allocate_largest_remainder,
    calculate_line,
    calculate_profit,
    round_money,
    round_percent,
)
from app.modules.pricing.models import Calculation
from app.modules.sales.models import SaleItem, SalesOrder, SalesReturn, SalesReturnItem


def _decimal_sum(values: Any) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = 60
        return sum(values, Decimal("0"))


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _rounded_output(value: Any, key: str | None = None) -> Any:
    if isinstance(value, Decimal):
        if key in {"margin_pct", "markup_pct"}:
            return str(round_percent(value))
        if key in {
            "quantity",
            "returned_quantity",
            "original_quantity",
            "remaining_quantity",
            "units_sold",
            "returned_units",
        }:
            return str(value)
        return str(round_money(value))
    if isinstance(value, dict):
        return {str(name): _rounded_output(item, str(name)) for name, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_rounded_output(item) for item in value]
    return value


def _record(
    db: Session,
    *,
    tenant_id: int,
    user_id: int,
    calc_type: str,
    input_data: dict[str, Any],
    output_data: dict[str, Any],
    warnings: list[str],
    source: str = "system",
) -> Calculation:
    canonical = json.dumps(
        {"formula_version": FORMULA_VERSION, "input": _json_value(input_data)},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    row = Calculation(
        tenant_id=tenant_id,
        calc_type=calc_type,
        formula_version=FORMULA_VERSION,
        input=_json_value(input_data),
        output=_rounded_output(output_data),
        warnings=sorted(set(warnings)),
        input_hash=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        source=source,
        created_by=user_id,
    )
    db.add(row)
    db.flush()
    return row


def calculate_order(db: Session, *, tenant_id: int, order_id: int, user_id: int) -> dict[str, Any]:
    order = db.scalar(
        select(SalesOrder).where(SalesOrder.id == order_id, SalesOrder.tenant_id == tenant_id)
    )
    if order is None:
        raise LookupError("NOT_FOUND")

    items = db.scalars(
        select(SaleItem)
        .where(SaleItem.tenant_id == tenant_id, SaleItem.order_id == order_id)
        .order_by(SaleItem.id)
    ).all()
    return_rows = db.execute(
        select(
            SalesReturnItem.id,
            SalesReturnItem.sale_item_id,
            SalesReturnItem.quantity,
            SalesReturnItem.refund_amount,
            SalesReturn.return_date,
        )
        .join(
            SalesReturn,
            (SalesReturn.id == SalesReturnItem.return_id)
            & (SalesReturn.tenant_id == SalesReturnItem.tenant_id),
        )
        .where(
            SalesReturn.tenant_id == tenant_id,
            SalesReturn.order_id == order_id,
            SalesReturn.status == "committed",
        )
        .order_by(SalesReturnItem.id)
    ).all()
    return_by_item: dict[int, tuple[Decimal, Decimal]] = {}
    return_snapshot: list[dict[str, Any]] = []
    for return_item_id, item_id, quantity, refund, return_date in return_rows:
        previous_quantity, previous_refund = return_by_item.get(
            int(item_id), (Decimal("0"), Decimal("0"))
        )
        return_by_item[int(item_id)] = (
            _decimal_sum((previous_quantity, Decimal(quantity))),
            _decimal_sum((previous_refund, Decimal(refund))),
        )
        return_snapshot.append(
            {
                "return_item_id": return_item_id,
                "sale_item_id": item_id,
                "quantity": quantity,
                "refund_amount": refund,
                "return_date": return_date.isoformat(),
            }
        )
    expenses = db.scalars(
        select(Expense)
        .where(
            Expense.tenant_id == tenant_id,
            Expense.allocation_scope == "order",
            Expense.order_id == order_id,
            Expense.deleted_at.is_(None),
        )
        .order_by(Expense.id)
    ).all()
    if any(expense.currency != order.currency for expense in expenses):
        raise ValueError("CURRENCY_MISMATCH")

    if order.status == "cancelled":
        expense_total = round_money(_decimal_sum(expense.amount for expense in expenses))
        warning = ["ORDER_CANCELLED_COST_UNATTRIBUTED"] if expense_total else []
        cancelled_output: dict[str, Any] = {
            "currency": order.currency,
            "revenue": Decimal("0"),
            "cogs": None,
            "gross_profit": None,
            "net_operating_profit": None,
            "margin_pct": None,
            "markup_pct": None,
            "allocated_expenses": Decimal("0"),
            "unallocated_expenses": expense_total,
            "lines": [],
        }
        input_data = {
            "order_id": order.id,
            "order_status": order.status,
            "currency": order.currency,
            "expenses": [
                {"id": e.id, "amount": e.amount, "scope": e.allocation_scope} for e in expenses
            ],
            "returns": [],
        }
        calculation = _record(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            calc_type="order",
            input_data=input_data,
            output_data=cancelled_output,
            warnings=warning,
        )
        cancelled_output = calculation.output
        db.commit()
        cancelled_output.update(
            {
                "formula_version": FORMULA_VERSION,
                "calculation_id": calculation.id,
                "warnings": warning,
            }
        )
        return cancelled_output

    line_results = []
    quantities: list[Decimal] = []
    input_lines: list[dict[str, Any]] = []
    output_lines: list[dict[str, Any]] = []
    for item in items:
        returned_quantity, refund_amount = return_by_item.get(item.id, (Decimal("0"), Decimal("0")))
        result = calculate_line(
            SaleLine(
                quantity=item.quantity,
                unit_price=item.unit_price,
                line_discount=item.line_discount,
                order_discount_share=item.order_discount_share,
                unit_cost=item.unit_cost,
                cost_source=item.cost_source,
                returned_quantity=returned_quantity,
                refund_amount=refund_amount,
            )
        )
        line_results.append(result)
        quantities.append(item.quantity)
        input_lines.append(
            {
                "sale_item_id": item.id,
                "quantity": item.quantity,
                "unit_price": item.unit_price,
                "line_discount": item.line_discount,
                "order_discount_share": item.order_discount_share,
                "unit_cost": item.unit_cost,
                "cost_source": item.cost_source,
                "returned_quantity": returned_quantity,
                "refund_amount": refund_amount,
            }
        )
        output_lines.append(
            {
                "sale_item_id": item.id,
                "net_line_revenue": result.net_line_revenue,
                "allocable_revenue": result.allocable_revenue,
                "recognized_revenue": result.recognized_revenue,
                "cogs_after_returns": result.cogs_after_returns,
                "gross_profit": result.gross_profit,
                "return_variance": result.return_variance,
                "return_gain": result.return_gain,
                "return_loss": result.return_loss,
                "warnings": list(result.warnings),
            }
        )

    expense_total = round_money(_decimal_sum(expense.amount for expense in expenses))
    if line_results and expense_total:
        weights = [result.allocable_revenue for result in line_results]
        if sum(weights, Decimal("0")) == Decimal("0"):
            allocations = tuple(Decimal("0") for _ in line_results)
        else:
            allocations = allocate_largest_remainder(expense_total, weights)
    else:
        allocations = tuple(Decimal("0") for _ in line_results)
    allocated_total = _decimal_sum(allocations)
    unallocated_total = expense_total - allocated_total
    profit = calculate_profit(line_results, allocations, unallocated_expenses=unallocated_total)
    warnings = list(profit.warnings)
    if unallocated_total:
        warnings.append("UNALLOCATED_ORDER_COSTS")
    output: dict[str, Any] = {
        "currency": order.currency,
        "revenue": profit.revenue,
        "known_cost_revenue": profit.known_cost_revenue,
        "unknown_cost_revenue": profit.unknown_cost_revenue,
        "cogs": profit.cogs,
        "gross_profit": profit.gross_profit,
        "net_operating_profit": profit.net_operating_profit,
        "margin_pct": profit.profit_margin_pct,
        "markup_pct": profit.markup_pct,
        "expenses": profit.expenses,
        "allocated_expenses": allocated_total,
        "unallocated_expenses": unallocated_total,
        "lines": output_lines,
    }
    input_data = {
        "order_id": order.id,
        "order_status": order.status,
        "currency": order.currency,
        "lines": input_lines,
        "returns": return_snapshot,
        "expenses": [
            {
                "id": e.id,
                "amount": e.amount,
                "currency": e.currency,
                "scope": e.allocation_scope,
                "expense_date": e.expense_date.isoformat(),
            }
            for e in expenses
        ],
        "allocation_strategy": "revenue_share",
    }
    calculation = _record(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        calc_type="order",
        input_data=input_data,
        output_data=output,
        warnings=warnings,
    )
    output = calculation.output
    db.commit()
    output.update(
        {
            "formula_version": FORMULA_VERSION,
            "calculation_id": calculation.id,
            "warnings": warnings,
        }
    )
    return output
