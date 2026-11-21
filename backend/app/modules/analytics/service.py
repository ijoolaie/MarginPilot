"""Shared, tenant-scoped FV-2 period analytics."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, localcontext
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.catalog.models import Product
from app.modules.expenses.models import Expense
from app.modules.pricing.engine import (
    FORMULA_VERSION,
    AllocationStrategy,
    SaleLine,
    allocate_expense,
    allocate_largest_remainder,
    calculate_line,
    calculate_profit,
    calculate_return_event,
    prorate_period_expense,
    round_money,
)
from app.modules.pricing.service import _record
from app.modules.sales.models import SaleItem, SalesOrder, SalesReturn, SalesReturnItem
from app.modules.tenancy.models import Tenant

Z = Decimal("0")


def _sum(values: Any) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = 60
        return sum(values, Z)


def _range(start: date, end: date) -> list[date]:
    if start > end:
        raise ValueError("INVALID_DATE_RANGE")
    if (end - start).days > 365:
        raise ValueError("DATE_RANGE_TOO_LARGE")
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def _profit(p: Any) -> dict[str, Any]:
    return {
        "revenue": p.revenue,
        "known_cost_revenue": p.known_cost_revenue,
        "unknown_cost_revenue": p.unknown_cost_revenue,
        "cogs": p.cogs,
        "gross_profit": p.gross_profit,
        "net_profit": p.net_operating_profit,
        "expenses": p.expenses,
        "margin_pct": p.profit_margin_pct,
        "markup_pct": p.markup_pct,
        "warnings": list(p.warnings),
    }


def _load(db: Session, tenant_id: int, start: date, end: date) -> dict[str, Any]:
    days = _range(start, end)
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise ValueError("TENANT_NOT_FOUND")
    orders = db.scalars(
        select(SalesOrder)
        .where(
            SalesOrder.tenant_id == tenant_id,
            SalesOrder.status == "completed",
            SalesOrder.order_date.between(start, end),
        )
        .order_by(SalesOrder.order_date, SalesOrder.id)
    ).all()
    om = {o.id: o for o in orders}
    items = db.scalars(
        select(SaleItem)
        .where(
            SaleItem.tenant_id == tenant_id, SaleItem.order_id.in_(om) if om else SaleItem.id == -1
        )
        .order_by(SaleItem.id)
    ).all()
    sales: list[dict[str, Any]] = []
    for item in items:
        o = om[item.order_id]
        result = calculate_line(
            SaleLine(
                quantity=item.quantity,
                unit_price=item.unit_price,
                line_discount=item.line_discount,
                order_discount_share=item.order_discount_share,
                unit_cost=item.unit_cost,
                cost_source=item.cost_source,
            )
        )
        sales.append(
            {"date": o.order_date, "order": o, "item": item, "result": result, "order_expense": Z}
        )
    returns: list[dict[str, Any]] = []
    rows = db.execute(
        select(
            SalesReturn.return_date,
            SalesReturn.id,
            SalesReturnItem.id,
            SalesReturnItem.sale_item_id,
            SalesReturnItem.quantity,
            SalesReturnItem.refund_amount,
        )
        .join(
            SalesReturnItem,
            (SalesReturnItem.return_id == SalesReturn.id)
            & (SalesReturnItem.tenant_id == SalesReturn.tenant_id),
        )
        .join(
            SalesOrder,
            (SalesOrder.id == SalesReturn.order_id)
            & (SalesOrder.tenant_id == SalesReturn.tenant_id),
        )
        .where(
            SalesReturn.tenant_id == tenant_id,
            SalesReturn.status == "committed",
            SalesReturn.return_date.between(start, end),
            SalesOrder.status == "completed",
        )
        .order_by(SalesReturn.return_date, SalesReturnItem.id)
    ).all()
    item_cache = {i.id: i for i in items}
    missing_ids = {row[3] for row in rows} - set(item_cache)
    if missing_ids:
        source_items = db.scalars(
            select(SaleItem).where(
                SaleItem.tenant_id == tenant_id,
                SaleItem.id.in_(missing_ids),
            )
        ).all()
        item_cache.update({item.id: item for item in source_items})
    for d, rid, riid, sid, qty, refund in rows:
        source_item = item_cache.get(sid)
        if source_item is None:
            raise ValueError("RETURN_SOURCE_ITEM_MISSING")
        result = calculate_return_event(
            original_quantity=source_item.quantity,
            unit_price=source_item.unit_price,
            line_discount=source_item.line_discount,
            order_discount_share=source_item.order_discount_share,
            returned_quantity=qty,
            refund_amount=refund,
            unit_cost=source_item.unit_cost,
            cost_source=source_item.cost_source,
        )
        returns.append(
            {
                "date": d,
                "return_id": rid,
                "return_item_id": riid,
                "item": source_item,
                "quantity": qty,
                "refund": refund,
                "result": result,
            }
        )
    returned_by_item: dict[int, tuple[Decimal, Decimal]] = {}
    for event in returns:
        sale_item_id = event["item"].id
        previous = returned_by_item.get(sale_item_id, (Z, Z))
        returned_by_item[sale_item_id] = (
            previous[0] + event["quantity"],
            previous[1] + event["refund"],
        )
    for sale in sales:
        item = sale["item"]
        returned_quantity, refund_amount = returned_by_item.get(item.id, (Z, Z))
        sale["allocation_result"] = calculate_line(
            SaleLine(
                quantity=item.quantity,
                unit_price=item.unit_price,
                line_discount=item.line_discount,
                order_discount_share=item.order_discount_share,
                returned_quantity=returned_quantity,
                refund_amount=refund_amount,
                unit_cost=item.unit_cost,
                cost_source=item.cost_source,
            )
        )
        sale["remaining_quantity"] = item.quantity - returned_quantity
    order_rows = db.scalars(
        select(Expense)
        .where(
            Expense.tenant_id == tenant_id,
            Expense.deleted_at.is_(None),
            Expense.allocation_scope == "order",
            Expense.order_id.in_(om) if om else Expense.id == -1,
        )
        .order_by(Expense.id)
    ).all()
    cancelled = db.scalars(
        select(Expense)
        .join(
            SalesOrder,
            (SalesOrder.id == Expense.order_id) & (SalesOrder.tenant_id == Expense.tenant_id),
        )
        .where(
            Expense.tenant_id == tenant_id,
            Expense.deleted_at.is_(None),
            Expense.allocation_scope == "order",
            Expense.expense_date.between(start, end),
            SalesOrder.status == "cancelled",
        )
        .order_by(Expense.id)
    ).all()
    period_rows = db.scalars(
        select(Expense)
        .where(
            Expense.tenant_id == tenant_id,
            Expense.deleted_at.is_(None),
            Expense.allocation_scope == "period",
            Expense.period_start <= end,
            Expense.period_end >= start,
        )
        .order_by(Expense.id)
    ).all()
    product_exp = db.scalars(
        select(Expense)
        .where(
            Expense.tenant_id == tenant_id,
            Expense.deleted_at.is_(None),
            Expense.allocation_scope == "product",
            Expense.expense_date.between(start, end),
        )
        .order_by(Expense.id)
    ).all()
    oe: dict[int, list[Expense]] = defaultdict(list)
    for expense in order_rows:
        if expense.order_id is not None:
            oe[expense.order_id].append(expense)
    pe: list[tuple[Expense, Decimal]] = []
    for expense in period_rows:
        if expense.period_start is None or expense.period_end is None:
            raise ValueError("INVALID_EXPENSE_PERIOD")
        share = prorate_period_expense(
            expense.amount, expense.period_start, expense.period_end, start, end
        )
        if share:
            pe.append((expense, share))
    unallocated_order = Z
    unallocated_order_by_date: dict[date, Decimal] = defaultdict(lambda: Z)
    for oid, costs in oe.items():
        group = [sale for sale in sales if sale["order"].id == oid]
        if any(expense.currency != om[oid].currency for expense in costs):
            raise ValueError("CURRENCY_MISMATCH")
        total = round_money(_sum(expense.amount for expense in costs))
        if not group:
            unallocated_order += total
            unallocated_order_by_date[om[oid].order_date] += total
            continue
        allocations, allocation_warnings = allocate_expense(
            total,
            [sale["allocation_result"] for sale in group],
            [sale["remaining_quantity"] for sale in group],
            "revenue_share",
        )
        if allocation_warnings:
            unallocated_order += total
            unallocated_order_by_date[om[oid].order_date] += total
            continue
        for event, amount in zip(group, allocations, strict=True):
            event["order_expense"] = amount
    currencies = (
        {o.currency for o in orders}
        | {e.currency for e in cancelled}
        | {e.currency for e, _ in pe}
        | {e.currency for e in product_exp}
    )
    if currencies - {tenant.currency_code}:
        raise ValueError("CURRENCY_MISMATCH")
    return {
        "days": days,
        "orders": orders,
        "sales": sales,
        "returns": returns,
        "order_expenses": oe,
        "unallocated_order": unallocated_order,
        "unallocated_order_by_date": unallocated_order_by_date,
        "cancelled": cancelled,
        "period_expenses": pe,
        "product_expenses": product_exp,
        "currency": tenant.currency_code,
    }


def _period_cost(d: dict[str, Any]) -> Decimal:
    return round_money(_sum(v for _, v in d["period_expenses"]))


def _inputs(d: dict[str, Any], start: date, end: date) -> dict[str, Any]:
    return {
        "date_from": start.isoformat(),
        "date_to": end.isoformat(),
        "currency": d["currency"],
        "sales": [
            {
                "sale_item_id": s["item"].id,
                "order_id": s["order"].id,
                "date": s["date"].isoformat(),
                "quantity": str(s["item"].quantity),
                "unit_price": str(s["item"].unit_price),
                "line_discount": str(s["item"].line_discount),
                "order_discount_share": str(s["item"].order_discount_share),
                "unit_cost": str(s["item"].unit_cost) if s["item"].unit_cost is not None else None,
                "cost_source": s["item"].cost_source,
            }
            for s in d["sales"]
        ],
        "returns": [
            {
                "return_id": r["return_id"],
                "return_item_id": r["return_item_id"],
                "sale_item_id": r["item"].id,
                "date": r["date"].isoformat(),
                "quantity": str(r["quantity"]),
                "refund": str(r["refund"]),
                "original_quantity": str(r["item"].quantity),
                "unit_price": str(r["item"].unit_price),
                "line_discount": str(r["item"].line_discount),
                "order_discount_share": str(r["item"].order_discount_share),
                "unit_cost": str(r["item"].unit_cost) if r["item"].unit_cost is not None else None,
                "cost_source": r["item"].cost_source,
            }
            for r in d["returns"]
        ],
        "period_expenses": [
            {
                "id": e.id,
                "amount": str(e.amount),
                "share": str(v),
                "period_start": e.period_start.isoformat(),
                "period_end": e.period_end.isoformat(),
                "allocation_strategy": e.allocation_strategy,
            }
            for e, v in d["period_expenses"]
        ],
        "order_expenses": [
            {
                "id": e.id,
                "order_id": e.order_id,
                "amount": str(e.amount),
                "currency": e.currency,
                "expense_date": e.expense_date.isoformat(),
            }
            for group in d["order_expenses"].values()
            for e in group
        ],
        "cancelled_order_expenses": [
            {
                "id": e.id,
                "order_id": e.order_id,
                "amount": str(e.amount),
                "expense_date": e.expense_date.isoformat(),
            }
            for e in d["cancelled"]
        ],
        "product_expenses": [
            {
                "id": e.id,
                "product_id": e.product_id,
                "amount": str(e.amount),
                "expense_date": e.expense_date.isoformat(),
            }
            for e in d["product_expenses"]
        ],
    }


def _journal(
    db: Session, tid: int, uid: int, kind: str, inputs: dict[str, Any], output: dict[str, Any]
) -> dict[str, Any]:
    warnings = list(output.get("warnings", []))
    row = _record(
        db,
        tenant_id=tid,
        user_id=uid,
        calc_type=kind,
        input_data=inputs,
        output_data=output,
        warnings=warnings,
        source="report",
    )
    result = dict(row.output)
    result.update(
        {"calculation_id": row.id, "formula_version": FORMULA_VERSION, "warnings": warnings}
    )
    return result


def summary(db: Session, tid: int, uid: int, start: date, end: date) -> dict[str, Any]:
    d = _load(db, tid, start, end)
    lines = [s["result"] for s in d["sales"]] + [r["result"] for r in d["returns"]]
    allocated = [s["order_expense"] for s in d["sales"]] + [Z for _ in d["returns"]]
    period = _period_cost(d)
    cancelled = round_money(_sum(e.amount for e in d["cancelled"]))
    unallocated_order = d["unallocated_order"]
    p = calculate_profit(
        lines, allocated, unallocated_expenses=period + cancelled + unallocated_order
    )
    warnings = set(p.warnings)
    if cancelled:
        warnings.add("CANCELLED_ORDER_COSTS_UNALLOCATED")
    if unallocated_order:
        warnings.add("UNALLOCATED_ORDER_COSTS")
    if period and not d["sales"]:
        warnings.add("UNALLOCATED_PERIOD_COSTS")
    out = {
        **_profit(p),
        "currency": d["currency"],
        "sales_count": len(d["orders"]),
        "units_sold": _sum(s["item"].quantity for s in d["sales"]),
        "returns_count": len({r["return_id"] for r in d["returns"]}),
        "returned_units": _sum(r["quantity"] for r in d["returns"]),
        "refunds": round_money(_sum(r["refund"] for r in d["returns"])),
        "return_variance": round_money(_sum(r["result"].return_variance for r in d["returns"])),
        "order_expenses": round_money(_sum(allocated) + unallocated_order),
        "unallocated_order_expenses": round_money(unallocated_order),
        "period_expenses": period,
        "cancelled_order_expenses": cancelled,
        "product_scoped_expenses_excluded": round_money(
            _sum(e.amount for e in d["product_expenses"])
        ),
        "warnings": sorted(warnings),
        "data_through": datetime.now(UTC).isoformat(),
    }
    result = _journal(db, tid, uid, "period", _inputs(d, start, end), out)
    db.commit()
    return result


def products_report(db: Session, tid: int, uid: int, start: date, end: date) -> dict[str, Any]:
    d = _load(db, tid, start, end)
    product_ids = {
        event["item"].product_id
        for event in d["sales"] + d["returns"]
        if event["item"].product_id is not None
    } | {expense.product_id for expense in d["product_expenses"] if expense.product_id is not None}
    products = db.scalars(
        select(Product)
        .where(
            Product.tenant_id == tid,
            Product.id.in_(product_ids) if product_ids else Product.id == -1,
        )
        .order_by(Product.id)
    ).all()
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for e in d["sales"] + d["returns"]:
        if e["item"].product_id is not None:
            grouped[e["item"].product_id].append(e)
    order_cost: dict[int, Decimal] = defaultdict(lambda: Z)
    unallocated_order = d["unallocated_order"]
    for e in d["sales"]:
        if e["item"].product_id is not None:
            order_cost[e["item"].product_id] += e["order_expense"]
        else:
            unallocated_order += e["order_expense"]
    direct: dict[int, Decimal] = defaultdict(lambda: Z)
    for e in d["product_expenses"]:
        if e.product_id is not None:
            direct[e.product_id] += e.amount
    data_through = datetime.now(UTC).isoformat()
    period_alloc: dict[int, Decimal] = defaultdict(lambda: Z)
    unallocated_period = Z
    strategy_totals: dict[AllocationStrategy, Decimal] = defaultdict(lambda: Z)
    for expense, share in d["period_expenses"]:
        strategy = cast(AllocationStrategy, expense.allocation_strategy or "revenue_share")
        strategy_totals[strategy] += share
    if strategy_totals and d["sales"]:
        strategies = list(strategy_totals)
        strategy_amounts = allocate_largest_remainder(
            _period_cost(d), [strategy_totals[strategy] for strategy in strategies]
        )
        for strategy, amount in zip(strategies, strategy_amounts, strict=True):
            alloc, allocation_warnings = allocate_expense(
                amount,
                [s["allocation_result"] for s in d["sales"]],
                [s["remaining_quantity"] for s in d["sales"]],
                strategy,
            )
            if allocation_warnings:
                unallocated_period += amount
                continue
            for sale, share_amount in zip(d["sales"], alloc, strict=True):
                if sale["item"].product_id is not None:
                    period_alloc[sale["item"].product_id] += share_amount
                else:
                    unallocated_period += share_amount
    rows = []
    ids = []
    for product in products:
        events = grouped.get(product.id, [])
        if (
            not events
            and not direct[product.id]
            and not order_cost[product.id]
            and not period_alloc[product.id]
        ):
            continue
        results = [e["result"] for e in events]
        order_alloc = [e["order_expense"] if "order" in e else Z for e in events]
        unallocated = (
            direct[product.id]
            + period_alloc[product.id]
            + order_cost[product.id]
            - _sum(order_alloc)
        )
        p = calculate_profit(results, order_alloc, unallocated_expenses=unallocated)
        out = {
            "product_id": product.id,
            "sku": product.sku,
            "name": product.name,
            "currency": d["currency"],
            "data_through": data_through,
            **_profit(p),
            "units_sold": _sum(e["item"].quantity for e in events if "order" in e),
            "returned_units": _sum(e["quantity"] for e in events if "return_id" in e),
            "direct_product_expenses": round_money(direct[product.id]),
            "allocated_order_expenses": round_money(order_cost[product.id]),
            "allocated_period_expenses": round_money(period_alloc[product.id]),
        }
        inputs = {
            "product_id": product.id,
            "date_from": start.isoformat(),
            "date_to": end.isoformat(),
            "events": [
                {
                    "kind": "return" if "return_id" in e else "sale",
                    "date": e["date"].isoformat(),
                    "sale_item_id": e["item"].id,
                    "return_id": e.get("return_id"),
                    "return_item_id": e.get("return_item_id"),
                    "quantity": str(e.get("quantity", e["item"].quantity)),
                    "refund": str(e.get("refund", Z)),
                    "unit_price": str(e["item"].unit_price),
                    "unit_cost": str(e["item"].unit_cost)
                    if e["item"].unit_cost is not None
                    else None,
                    "cost_source": e["item"].cost_source,
                    "line_discount": str(e["item"].line_discount),
                    "order_discount_share": str(e["item"].order_discount_share),
                }
                for e in events
            ],
            "direct_product_expenses": str(direct[product.id]),
            "order_expenses": str(order_cost[product.id]),
            "period_expenses": str(period_alloc[product.id]),
        }
        result = _journal(db, tid, uid, "product", inputs, out)
        ids.append(result["calculation_id"])
        rows.append(result)
    unallocated_period += _period_cost(d) if not d["sales"] else Z
    response = {
        "date_from": start.isoformat(),
        "date_to": end.isoformat(),
        "currency": d["currency"],
        "products": rows,
        "unallocated_period_expenses": round_money(unallocated_period),
        "unallocated_order_expenses": round_money(unallocated_order),
        "cancelled_order_expenses": round_money(_sum(e.amount for e in d["cancelled"])),
        "warnings": (
            (["UNALLOCATED_PERIOD_COSTS"] if unallocated_period else [])
            + (["UNALLOCATED_ORDER_COSTS"] if unallocated_order else [])
            + (["CANCELLED_ORDER_COSTS_UNATTRIBUTED"] if d["cancelled"] else [])
        ),
        "formula_version": FORMULA_VERSION,
        "data_through": data_through,
        "calculation_ids": ids,
    }
    db.commit()
    return response


def expenses_report(db: Session, tid: int, uid: int, start: date, end: date) -> dict[str, Any]:
    d = _load(db, tid, start, end)
    groups: dict[tuple[str, str], Decimal] = defaultdict(lambda: Z)
    for costs in d["order_expenses"].values():
        for e in costs:
            groups[(e.type, "order")] += e.amount
    for e in d["cancelled"]:
        groups[(e.type, "cancelled_order_unallocated")] += e.amount
    for e, _share in d["period_expenses"]:
        groups[(e.type, "period")] += _share
    for e in d["product_expenses"]:
        groups[(e.type, "product_excluded_from_period_profit")] += e.amount
    rows = [
        {"type": k[0], "scope": k[1], "amount": round_money(v), "currency": d["currency"]}
        for k, v in sorted(groups.items())
    ]
    included = round_money(
        _sum(
            v for (_, scope), v in groups.items() if scope != "product_excluded_from_period_profit"
        )
    )
    out = {
        "date_from": start.isoformat(),
        "date_to": end.isoformat(),
        "currency": d["currency"],
        "items": rows,
        "total_in_period_profit": included,
        "product_scoped_excluded": round_money(
            _sum(
                v
                for (_, scope), v in groups.items()
                if scope == "product_excluded_from_period_profit"
            )
        ),
        "warnings": ["CANCELLED_ORDER_COSTS_UNALLOCATED"] if d["cancelled"] else [],
        "data_through": datetime.now(UTC).isoformat(),
    }
    result = _journal(db, tid, uid, "period", _inputs(d, start, end), out)
    db.commit()
    return result


def trends_report(
    db: Session, tid: int, uid: int, start: date, end: date, group_by: str
) -> dict[str, Any]:
    d = _load(db, tid, start, end)
    buckets: dict[str, dict[str, Decimal]] = defaultdict(
        lambda: {"revenue": Z, "refunds": Z, "cogs": Z, "expenses": Z}
    )
    unknown: set[str] = set()

    def key(day: date) -> str:
        return day.isoformat() if group_by == "day" else day.strftime("%Y-%m")

    for e in d["sales"]:
        b = buckets[key(e["date"])]
        b["revenue"] += e["result"].recognized_revenue
        if e["result"].cogs_after_returns is None:
            unknown.add(key(e["date"]))
        else:
            b["cogs"] += e["result"].cogs_after_returns
        b["expenses"] += e["order_expense"]
    for e in d["returns"]:
        b = buckets[key(e["date"])]
        b["refunds"] += e["refund"]
        b["revenue"] -= e["refund"]
        if e["result"].cogs_after_returns is None:
            unknown.add(key(e["date"]))
        else:
            b["cogs"] += e["result"].cogs_after_returns
    for event_date, amount in d["unallocated_order_by_date"].items():
        buckets[key(event_date)]["expenses"] += amount
    for e in d["cancelled"]:
        buckets[key(e.expense_date)]["expenses"] += e.amount
    for e, _share in d["period_expenses"]:
        for day in d["days"]:
            buckets[key(day)]["expenses"] += prorate_period_expense(
                e.amount, e.period_start, e.period_end, day, day
            )
    labels = sorted(buckets)
    rows = [
        {
            "period": label,
            **{k: round_money(v) for k, v in buckets[label].items()},
            "gross_profit": None
            if label in unknown
            else round_money(buckets[label]["revenue"] - buckets[label]["cogs"]),
        }
        for label in labels
    ]
    out = {
        "date_from": start.isoformat(),
        "date_to": end.isoformat(),
        "group_by": group_by,
        "currency": d["currency"],
        "items": rows,
        "warnings": (["COST_UNKNOWN"] if unknown else [])
        + (["CANCELLED_ORDER_COSTS_UNALLOCATED"] if d["cancelled"] else []),
        "data_through": datetime.now(UTC).isoformat(),
    }
    result = _journal(db, tid, uid, "period", _inputs(d, start, end), out)
    db.commit()
    return result
