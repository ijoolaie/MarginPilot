from decimal import Decimal

import pytest

from app.modules.sales.allocation import (
    allocate_order_discount,
    post_line_discount_basis,
)


def test_proportional_allocation_uses_post_line_discount_bases() -> None:
    result = allocate_order_discount([Decimal("60"), Decimal("40")], Decimal("10"))
    assert result == (Decimal("6"), Decimal("4"))


def test_largest_remainder_tie_breaks_by_original_line_order() -> None:
    result = allocate_order_discount([Decimal("1"), Decimal("1"), Decimal("1")], Decimal("2"))
    assert result == (Decimal("1"), Decimal("1"), Decimal("0"))


def test_allocations_sum_exactly_to_order_discount() -> None:
    result = allocate_order_discount([Decimal("100"), Decimal("50"), Decimal("25")], Decimal("17"))
    assert sum(result, Decimal("0")) == Decimal("17")


def test_zero_discount_with_zero_bases_returns_zeros() -> None:
    assert allocate_order_discount([Decimal("0"), Decimal("0")], Decimal("0")) == (
        Decimal("0"),
        Decimal("0"),
    )


def test_positive_discount_over_zero_bases_is_rejected() -> None:
    with pytest.raises(ValueError, match="zero-value"):
        allocate_order_discount([Decimal("0")], Decimal("1"))


def test_discount_cannot_exceed_post_line_discount_value() -> None:
    with pytest.raises(ValueError, match="cannot exceed"):
        allocate_order_discount([Decimal("5"), Decimal("3")], Decimal("9"))


def test_non_integral_currency_quantum_is_rejected() -> None:
    with pytest.raises(ValueError, match="multiple"):
        allocate_order_discount([Decimal("10")], Decimal("1.5"))


def test_post_line_discount_basis_uses_quantity_and_line_discount() -> None:
    assert post_line_discount_basis(Decimal("2.5"), Decimal("100"), Decimal("25")) == Decimal("225")


def test_line_discount_cannot_exceed_gross_value() -> None:
    with pytest.raises(ValueError, match="gross line value"):
        post_line_discount_basis(Decimal("1"), Decimal("10"), Decimal("11"))


def test_high_precision_inputs_preserve_exact_total_allocation() -> None:
    bases = [
        Decimal("999999999999999999.99"),
        Decimal("888888888888888888.88"),
        Decimal("777777777777777777.77"),
    ]
    result = allocate_order_discount(bases, Decimal("999999999999999999"))
    assert sum(result, Decimal("0")) == Decimal("999999999999999999")


def test_allocation_ignores_low_global_decimal_precision() -> None:
    from decimal import getcontext

    previous_precision = getcontext().prec
    try:
        getcontext().prec = 6
        result = allocate_order_discount(
            [Decimal("1.000000"), Decimal("1.000001")], Decimal("1")
        )
    finally:
        getcontext().prec = previous_precision

    assert result == (Decimal("0"), Decimal("1"))
