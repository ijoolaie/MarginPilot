"""Pure Decimal calculation primitives implementing FV-2."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal, localcontext
from typing import Literal

ZERO = Decimal("0")
ONE = Decimal("1")
QUANTUM = Decimal("1")
FORMULA_VERSION = "FV-2"
AllocationStrategy = Literal["revenue_share", "equal_quantity", "equal_count"]


@dataclass(frozen=True, slots=True)
class SaleLine:
    quantity: Decimal
    unit_price: Decimal
    line_discount: Decimal = ZERO
    order_discount_share: Decimal = ZERO
    unit_cost: Decimal | None = None
    cost_source: str = "unknown"
    returned_quantity: Decimal = ZERO
    refund_amount: Decimal = ZERO


@dataclass(frozen=True, slots=True)
class LineResult:
    net_line_revenue: Decimal
    allocable_revenue: Decimal
    recognized_revenue: Decimal
    cogs_after_returns: Decimal | None
    return_variance: Decimal
    return_gain: Decimal
    return_loss: Decimal
    gross_profit: Decimal | None
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProfitResult:
    revenue: Decimal
    known_cost_revenue: Decimal
    unknown_cost_revenue: Decimal
    cogs: Decimal | None
    expenses: Decimal
    gross_profit: Decimal | None
    net_operating_profit: Decimal | None
    profit_margin_pct: Decimal | None
    markup_pct: Decimal | None
    warnings: tuple[str, ...]


def round_money(value: Decimal, quantum: Decimal = QUANTUM) -> Decimal:
    if not isinstance(value, Decimal) or not isinstance(quantum, Decimal):
        raise TypeError("money values must be Decimal")
    if quantum <= ZERO:
        raise ValueError("currency quantum must be positive")
    with localcontext() as ctx:
        ctx.prec = 60
        return value.quantize(quantum, rounding=ROUND_HALF_UP)


def round_percent(value: Decimal) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError("percentage must be Decimal")
    with localcontext() as ctx:
        ctx.prec = 60
        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def allocate_largest_remainder(
    amount: Decimal, weights: Sequence[Decimal], quantum: Decimal = QUANTUM
) -> tuple[Decimal, ...]:
    if not isinstance(amount, Decimal) or not isinstance(quantum, Decimal):
        raise TypeError("allocation values must be Decimal")
    if amount < ZERO or quantum <= ZERO:
        raise ValueError("amount must be non-negative and quantum positive")
    if any(not isinstance(w, Decimal) or w < ZERO for w in weights):
        raise ValueError("weights must be non-negative Decimal values")
    if not weights:
        if amount:
            raise ValueError("cannot allocate positive amount to no rows")
        return ()
    with localcontext() as ctx:
        ctx.prec = 60
        units = amount / quantum
        if units != units.to_integral_value():
            raise ValueError("amount must be a multiple of currency quantum")
        total = sum(weights, ZERO)
        if total == ZERO:
            if amount:
                raise ValueError("cannot allocate against zero total weight")
            return tuple(ZERO for _ in weights)
        quotas = [units * weight / total for weight in weights]
        floors = [q.to_integral_value(rounding=ROUND_FLOOR) for q in quotas]
        remainder = int(units - sum(floors, ZERO))
        order = sorted(range(len(weights)), key=lambda i: (-(quotas[i] - floors[i]), i))
        for index in order[:remainder]:
            floors[index] += ONE
        result = tuple(value * quantum for value in floors)
        if sum(result, ZERO) != amount:
            raise ArithmeticError("allocation did not preserve total")
        return result


def calculate_line(line: SaleLine) -> LineResult:
    fields = (
        "quantity",
        "unit_price",
        "line_discount",
        "order_discount_share",
        "returned_quantity",
        "refund_amount",
    )
    for field in fields:
        if not isinstance(getattr(line, field), Decimal):
            raise TypeError(f"{field} must be Decimal")
    if line.unit_cost is not None and not isinstance(line.unit_cost, Decimal):
        raise TypeError("unit_cost must be Decimal")
    if line.quantity <= ZERO or line.unit_price < ZERO:
        raise ValueError("quantity must be positive and unit_price non-negative")
    if (
        min(
            line.line_discount,
            line.order_discount_share,
            line.returned_quantity,
            line.refund_amount,
        )
        < ZERO
    ):
        raise ValueError("discount, return quantity and refund must be non-negative")
    if line.returned_quantity > line.quantity:
        raise ValueError("returned_quantity cannot exceed quantity")
    with localcontext() as ctx:
        ctx.prec = 60
        gross = line.quantity * line.unit_price
        nlr = gross - line.line_discount - line.order_discount_share
        if nlr < ZERO:
            raise ValueError("discounts cannot exceed gross line value")
        returned_value = nlr / line.quantity * line.returned_quantity
        allocable = nlr - returned_value
        revenue = nlr - line.refund_amount
        variance = line.refund_amount - returned_value
        warnings: list[str] = []
        if line.cost_source == "unknown" or line.unit_cost is None:
            cogs_after = None
            gross_profit = None
            warnings.append("COST_UNKNOWN")
        else:
            cogs_after = (line.quantity - line.returned_quantity) * line.unit_cost
            gross_profit = revenue - cogs_after
        if revenue == ZERO:
            warnings.append("ZERO_REVENUE")
        return LineResult(
            net_line_revenue=nlr,
            allocable_revenue=allocable,
            recognized_revenue=revenue,
            cogs_after_returns=cogs_after,
            return_variance=variance,
            return_gain=max(-variance, ZERO),
            return_loss=max(variance, ZERO),
            gross_profit=gross_profit,
            warnings=tuple(warnings),
        )


def calculate_return_event(
    *,
    original_quantity: Decimal,
    unit_price: Decimal,
    line_discount: Decimal,
    order_discount_share: Decimal,
    returned_quantity: Decimal,
    refund_amount: Decimal,
    unit_cost: Decimal | None,
    cost_source: str,
) -> LineResult:
    """Calculate a physical return as a dated negative financial event.

    This lets period reporting recognize a return on return_date without
    backdating its revenue/COGS effects into the original sale period.
    """
    values = (
        original_quantity,
        unit_price,
        line_discount,
        order_discount_share,
        returned_quantity,
        refund_amount,
    )
    if any(not isinstance(value, Decimal) for value in values):
        raise TypeError("return event financial values must be Decimal")
    if unit_cost is not None and not isinstance(unit_cost, Decimal):
        raise TypeError("unit_cost must be Decimal")
    if original_quantity <= ZERO or returned_quantity <= ZERO:
        raise ValueError("original and returned quantities must be positive")
    if returned_quantity > original_quantity:
        raise ValueError("returned_quantity cannot exceed original quantity")
    if min(unit_price, line_discount, order_discount_share, refund_amount) < ZERO:
        raise ValueError("return event monetary values must be non-negative")

    with localcontext() as ctx:
        ctx.prec = 60
        net_line_revenue = original_quantity * unit_price - line_discount - order_discount_share
        if net_line_revenue < ZERO:
            raise ValueError("discounts cannot exceed gross line value")
        returned_net_value = net_line_revenue / original_quantity * returned_quantity
        revenue_effect = -refund_amount
        variance = refund_amount - returned_net_value
        warnings: list[str] = []
        if cost_source == "unknown" or unit_cost is None:
            cogs_effect = None
            gross_effect = None
            warnings.append("COST_UNKNOWN")
        else:
            cogs_effect = -(returned_quantity * unit_cost)
            gross_effect = revenue_effect - cogs_effect
        if revenue_effect == ZERO:
            warnings.append("ZERO_REVENUE")
        return LineResult(
            net_line_revenue=ZERO,
            allocable_revenue=ZERO,
            recognized_revenue=revenue_effect,
            cogs_after_returns=cogs_effect,
            return_variance=variance,
            return_gain=max(-variance, ZERO),
            return_loss=max(variance, ZERO),
            gross_profit=gross_effect,
            warnings=tuple(warnings),
        )


def prorate_period_expense(
    amount: Decimal,
    period_start: date,
    period_end: date,
    report_start: date,
    report_end: date,
) -> Decimal:
    """Return the unrounded share of a period expense overlapping a report.

    Both ranges are inclusive. Keep the prorated value unrounded so callers can
    aggregate period expenses before applying the currency quantum once.
    """
    if not isinstance(amount, Decimal):
        raise TypeError("expense amount must be Decimal")
    if amount < ZERO:
        raise ValueError("expense amount must be non-negative")
    if not all(
        isinstance(value, date) for value in (period_start, period_end, report_start, report_end)
    ):
        raise TypeError("period and report boundaries must be dates")
    if period_start > period_end:
        raise ValueError("expense period start must not exceed end")
    if report_start > report_end:
        raise ValueError("report start must not exceed end")

    overlap_start = max(period_start, report_start)
    overlap_end = min(period_end, report_end)
    if overlap_start > overlap_end:
        return ZERO

    overlap_days = (overlap_end - overlap_start).days + 1
    period_days = (period_end - period_start).days + 1
    with localcontext() as ctx:
        ctx.prec = 60
        return amount * Decimal(overlap_days) / Decimal(period_days)


def allocate_expense(
    amount: Decimal,
    lines: Sequence[LineResult],
    quantities: Sequence[Decimal],
    strategy: AllocationStrategy,
    quantum: Decimal = QUANTUM,
) -> tuple[tuple[Decimal, ...], tuple[str, ...]]:
    if len(lines) != len(quantities):
        raise ValueError("lines and quantities must have the same length")
    if any(not isinstance(q, Decimal) or q < ZERO for q in quantities):
        raise ValueError("quantities must be non-negative Decimal values")
    if strategy == "revenue_share":
        weights = [line.allocable_revenue for line in lines]
        with localcontext() as ctx:
            ctx.prec = 60
            zero_revenue = sum(weights, ZERO) == ZERO
        if zero_revenue:
            return tuple(ZERO for _ in lines), ("UNALLOCATED_PERIOD_COSTS",)
    elif strategy == "equal_quantity":
        weights = list(quantities)
    elif strategy == "equal_count":
        weights = [ONE if quantity > ZERO else ZERO for quantity in quantities]
    else:
        raise ValueError("unsupported allocation strategy")
    with localcontext() as ctx:
        ctx.prec = 60
        no_basis = sum(weights, ZERO) == ZERO
    if no_basis:
        return tuple(ZERO for _ in lines), ("UNALLOCATED_PERIOD_COSTS",)
    return allocate_largest_remainder(amount, weights, quantum), ()


def calculate_profit(
    lines: Sequence[LineResult],
    expenses: Sequence[Decimal],
    unallocated_expenses: Decimal = ZERO,
) -> ProfitResult:
    if len(lines) != len(expenses):
        raise ValueError("each line must have one expense allocation")
    if any(not isinstance(e, Decimal) or e < ZERO for e in expenses):
        raise ValueError("expenses must be non-negative Decimal values")
    with localcontext() as ctx:
        ctx.prec = 60
        revenue = sum((line.recognized_revenue for line in lines), ZERO)
        known = sum(
            (line.recognized_revenue for line in lines if line.gross_profit is not None), ZERO
        )
        unknown = revenue - known
        total_expenses = sum(expenses, ZERO) + unallocated_expenses
        if any(line.gross_profit is None for line in lines):
            cogs = gross = net = None
        else:
            cogs = sum((line.cogs_after_returns or ZERO for line in lines), ZERO)
            gross = revenue - cogs
            net = gross - total_expenses
        warnings = {warning for line in lines for warning in line.warnings}
        if revenue == ZERO:
            warnings.add("ZERO_REVENUE")
        cost_basis = None if cogs is None else cogs + total_expenses
        margin = None if revenue == ZERO or net is None else round_percent(net / revenue * 100)
        markup = (
            None
            if cost_basis is None or cost_basis == ZERO or net is None
            else round_percent(net / cost_basis * 100)
        )
        if cost_basis == ZERO:
            warnings.add("NO_COST_BASIS")
        return ProfitResult(
            revenue,
            known,
            unknown,
            cogs,
            total_expenses,
            gross,
            net,
            margin,
            markup,
            tuple(sorted(warnings)),
        )


def suggest_price(total_cost: Decimal, target_margin: Decimal) -> Decimal:
    if not isinstance(total_cost, Decimal) or not isinstance(target_margin, Decimal):
        raise TypeError("pricing inputs must be Decimal")
    if total_cost < ZERO or target_margin < ZERO or target_margin >= ONE:
        raise ValueError("cost must be non-negative and target margin in [0, 1)")
    with localcontext() as ctx:
        ctx.prec = 60
        return round_money(total_cost / (ONE - target_margin))


def validate_currency(currencies: Sequence[str]) -> str:
    if not currencies or len(set(currencies)) != 1 or currencies[0] not in {"IRT", "IRR"}:
        raise ValueError("CURRENCY_MISMATCH")
    return currencies[0]


def validate_expense_scope(
    scope: str,
    *,
    order_id: int | None = None,
    product_id: int | None = None,
    period_start: object | None = None,
    period_end: object | None = None,
) -> str:
    valid = (
        (
            scope == "order"
            and order_id is not None
            and product_id is None
            and period_start is None
            and period_end is None
        )
        or (
            scope == "product"
            and product_id is not None
            and order_id is None
            and period_start is None
            and period_end is None
        )
        or (
            scope == "period"
            and order_id is None
            and product_id is None
            and period_start is not None
            and period_end is not None
        )
    )
    if not valid:
        raise ValueError("INVALID_ALLOCATION_SCOPE")
    return scope


def cancelled_order_costs(amounts: Sequence[Decimal]) -> tuple[Decimal, tuple[str, ...]]:
    if any(not isinstance(amount, Decimal) or amount < ZERO for amount in amounts):
        raise ValueError("cancelled order costs must be non-negative Decimal values")
    total = sum(amounts, ZERO)
    return total, (("ORDER_CANCELLED_COST_UNATTRIBUTED",) if total else ())
