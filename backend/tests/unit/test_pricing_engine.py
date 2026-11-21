from datetime import date
from decimal import Decimal, localcontext

import pytest

from app.modules.pricing.engine import (
    SaleLine,
    allocate_expense,
    allocate_largest_remainder,
    calculate_line,
    calculate_profit,
    calculate_return_event,
    cancelled_order_costs,
    prorate_period_expense,
    suggest_price,
    validate_currency,
    validate_expense_scope,
)

D = Decimal


def line(**changes: object) -> SaleLine:
    values: dict[str, object] = {
        "quantity": D("10"),
        "unit_price": D("100000"),
        "line_discount": D("50000"),
        "unit_cost": D("60000"),
        "cost_source": "explicit",
    }
    values.update(changes)
    return SaleLine(**values)  # type: ignore[arg-type]


def test_v1_gross_profit() -> None:
    result = calculate_line(line())
    assert result.net_line_revenue == D("950000")
    assert result.gross_profit == D("350000")


def test_v2_net_profit_and_margin() -> None:
    result = calculate_profit([calculate_line(line())], [D("60000")])
    assert result.net_operating_profit == D("290000")
    assert result.profit_margin_pct == D("30.53")


def test_v3_markup() -> None:
    result = calculate_profit([calculate_line(line())], [D("60000")])
    assert result.markup_pct == D("43.94")


def test_v4_target_margin_price() -> None:
    assert suggest_price(D("600000"), D("0.25")) == D("800000")


def test_v5_margin_one_rejected() -> None:
    with pytest.raises(ValueError):
        suggest_price(D("100"), D("1"))


def test_v6_discount_applied_once() -> None:
    result = calculate_line(line(order_discount_share=D("10000")))
    assert result.net_line_revenue == D("940000")
    assert result.gross_profit == D("340000")


def test_v7_period_input_excludes_cancelled_order() -> None:
    # Eligibility is applied by the repository/service boundary before this pure engine.
    result = calculate_profit([calculate_line(line())], [D("0")])
    assert (result.revenue, result.cogs) == (D("950000"), D("600000"))


def test_v8_partial_return_gain() -> None:
    result = calculate_line(line(returned_quantity=D("2"), refund_amount=D("180000")))
    assert (result.return_variance, result.return_gain, result.return_loss) == (
        D("-10000"),
        D("10000"),
        D("0"),
    )
    assert result.gross_profit == D("290000")


def test_v8b_partial_return_loss() -> None:
    result = calculate_line(line(returned_quantity=D("2"), refund_amount=D("200000")))
    assert (result.return_variance, result.return_gain, result.return_loss) == (
        D("10000"),
        D("0"),
        D("10000"),
    )
    assert result.gross_profit == D("270000")


def test_v9_zero_revenue_margin_null() -> None:
    result = calculate_profit(
        [calculate_line(SaleLine(D("1"), D("0"), unit_cost=D("50"), cost_source="explicit"))],
        [D("0")],
    )
    assert result.gross_profit == D("-50")
    assert result.profit_margin_pct is None
    assert "ZERO_REVENUE" in result.warnings


def test_v10_equal_count_largest_remainder() -> None:
    assert allocate_largest_remainder(D("100"), [D("1")] * 3) == (D("34"), D("33"), D("33"))


def test_v11_revenue_share() -> None:
    rows = [
        calculate_line(SaleLine(D("1"), D("60000"), unit_cost=D("0"), cost_source="explicit")),
        calculate_line(SaleLine(D("1"), D("40000"), unit_cost=D("0"), cost_source="explicit")),
    ]
    shares, warnings = allocate_expense(D("100"), rows, [D("1"), D("1")], "revenue_share")
    assert shares == (D("60"), D("40"))
    assert warnings == ()


def test_v12_currency_mismatch() -> None:
    with pytest.raises(ValueError, match="CURRENCY_MISMATCH"):
        validate_currency(["IRT", "IRR"])


def test_v13_percent_rounds_half_up() -> None:
    from app.modules.pricing.engine import round_percent

    assert round_percent(D("43.939393")) == D("43.94")


def test_v14_zero_cost_basis_markup_null() -> None:
    result = calculate_profit(
        [calculate_line(SaleLine(D("1"), D("0"), unit_cost=D("0"), cost_source="explicit"))],
        [D("0")],
    )
    assert result.markup_pct is None
    assert "NO_COST_BASIS" in result.warnings


def test_v15_zero_revenue_period_expense_is_unallocated() -> None:
    rows = [calculate_line(SaleLine(D("1"), D("0"), unit_cost=D("0"), cost_source="explicit"))]
    shares, warnings = allocate_expense(D("100"), rows, [D("1")], "revenue_share")
    assert shares == (D("0"),)
    assert warnings == ("UNALLOCATED_PERIOD_COSTS",)


def test_v16_full_return() -> None:
    result = calculate_line(line(returned_quantity=D("10"), refund_amount=D("950000")))
    assert result.return_variance == D("0")
    assert result.return_loss == D("0")
    assert result.gross_profit == D("0")


def test_v17_cancelled_order_cost_is_unattributed() -> None:
    assert cancelled_order_costs([D("20000")]) == (
        D("20000"),
        ("ORDER_CANCELLED_COST_UNATTRIBUTED",),
    )


def test_v18_unknown_cost_is_not_zero() -> None:
    result = calculate_profit(
        [calculate_line(line(unit_cost=None, cost_source="unknown"))], [D("0")]
    )
    assert result.cogs is None
    assert result.unknown_cost_revenue == D("950000")
    assert "COST_UNKNOWN" in result.warnings


def test_v19_expense_scopes_are_mutually_exclusive() -> None:
    assert validate_expense_scope("order", order_id=1) == "order"
    assert validate_expense_scope("product", product_id=1) == "product"
    assert (
        validate_expense_scope("period", period_start="2026-01-01", period_end="2026-01-31")
        == "period"
    )
    with pytest.raises(ValueError):
        validate_expense_scope("period", order_id=1)


def test_v20_expense_allocation_uses_post_return_revenue() -> None:
    rows = [
        calculate_line(line(returned_quantity=D("5"), refund_amount=D("475000"))),
        calculate_line(line()),
    ]
    shares, warnings = allocate_expense(D("30000"), rows, [D("10"), D("10")], "revenue_share")
    assert shares == (D("10000"), D("20000"))
    assert warnings == ()


def test_financial_math_ignores_low_global_decimal_precision() -> None:
    from decimal import getcontext

    from app.modules.pricing.engine import round_money

    previous = getcontext().prec
    try:
        getcontext().prec = 6
        result = calculate_line(
            SaleLine(
                D("1"),
                D("99999999999999999999"),
                unit_cost=D("1"),
                cost_source="explicit",
            )
        )
        profit = calculate_profit([result], [D("0")])
        rounded = round_money(D("99999999999999999999.50"))
    finally:
        getcontext().prec = previous

    assert result.gross_profit == D("99999999999999999998")
    assert profit.gross_profit == D("99999999999999999998")
    assert rounded == D("100000000000000000000")


def test_unallocated_expenses_reduce_net_profit_without_reallocation() -> None:
    line_result = calculate_line(line())
    result = calculate_profit([line_result], [D("0")], unallocated_expenses=D("25"))
    assert result.expenses == D("25")
    assert result.net_operating_profit == D("349975")


def test_equal_count_excludes_fully_returned_lines() -> None:
    rows = [
        calculate_line(line(returned_quantity=D("10"), refund_amount=D("950000"))),
        calculate_line(line()),
    ]
    shares, warnings = allocate_expense(D("10"), rows, [D("0"), D("10")], "equal_count")
    assert shares == (D("0"), D("10"))
    assert warnings == ()


def test_period_expense_without_remaining_quantity_stays_unallocated() -> None:
    rows = [calculate_line(line(returned_quantity=D("10"), refund_amount=D("950000")))]
    shares, warnings = allocate_expense(D("10"), rows, [D("0")], "equal_quantity")
    assert shares == (D("0"),)
    assert warnings == ("UNALLOCATED_PERIOD_COSTS",)


def test_period_expense_prorates_inclusive_overlap_days() -> None:
    share = prorate_period_expense(
        D("30000000"),
        date(2026, 11, 1),
        date(2026, 11, 30),
        date(2026, 11, 16),
        date(2026, 11, 30),
    )
    assert share == D("15000000")


def test_period_expense_full_overlap_returns_full_amount() -> None:
    amount = D("123.45")
    assert (
        prorate_period_expense(
            amount, date(2026, 11, 1), date(2026, 11, 30), date(2026, 11, 1), date(2026, 11, 30)
        )
        == amount
    )


def test_period_expense_without_overlap_returns_zero() -> None:
    assert prorate_period_expense(
        D("100"), date(2026, 11, 1), date(2026, 11, 10), date(2026, 11, 11), date(2026, 11, 20)
    ) == D("0")


def test_period_expense_proration_keeps_fractional_minor_units_unrounded() -> None:
    share = prorate_period_expense(
        D("100"),
        date(2026, 11, 1),
        date(2026, 11, 30),
        date(2026, 11, 1),
        date(2026, 11, 10),
    )
    with localcontext() as ctx:
        ctx.prec = 60
        assert share == D("100") / D("3")


def test_period_expense_rejects_invalid_ranges_and_non_decimal_amount() -> None:
    with pytest.raises(TypeError, match="Decimal"):
        prorate_period_expense(
            100, date(2026, 11, 1), date(2026, 11, 2), date(2026, 11, 1), date(2026, 11, 2)
        )  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="expense period"):
        prorate_period_expense(
            D("10"), date(2026, 11, 2), date(2026, 11, 1), date(2026, 11, 1), date(2026, 11, 2)
        )
    with pytest.raises(ValueError, match="report start"):
        prorate_period_expense(
            D("10"), date(2026, 11, 1), date(2026, 11, 2), date(2026, 11, 2), date(2026, 11, 1)
        )


@pytest.mark.parametrize(
    ("refund", "expected_gross", "expected_variance"),
    [
        (Decimal("180"), Decimal("-60"), Decimal("-10")),
        (Decimal("200"), Decimal("-80"), Decimal("10")),
    ],
)
def test_return_event_is_recognized_on_return_date(
    refund: Decimal, expected_gross: Decimal, expected_variance: Decimal
) -> None:
    result = calculate_return_event(
        original_quantity=Decimal("10"),
        unit_price=Decimal("100"),
        line_discount=Decimal("50"),
        order_discount_share=Decimal("0"),
        returned_quantity=Decimal("2"),
        refund_amount=refund,
        unit_cost=Decimal("60"),
        cost_source="explicit",
    )
    assert result.recognized_revenue == -refund
    assert result.cogs_after_returns == Decimal("-120")
    assert result.gross_profit == expected_gross
    assert result.return_variance == expected_variance


def test_return_event_keeps_unknown_cost_unknown() -> None:
    result = calculate_return_event(
        original_quantity=Decimal("1"),
        unit_price=Decimal("100"),
        line_discount=Decimal("0"),
        order_discount_share=Decimal("0"),
        returned_quantity=Decimal("1"),
        refund_amount=Decimal("100"),
        unit_cost=None,
        cost_source="unknown",
    )
    assert result.recognized_revenue == Decimal("-100")
    assert result.cogs_after_returns is None
    assert result.gross_profit is None
    assert "COST_UNKNOWN" in result.warnings
