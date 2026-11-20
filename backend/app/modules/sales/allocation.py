"""Deterministic order-discount allocation using largest remainder."""

from collections.abc import Sequence
from decimal import ROUND_FLOOR, Decimal, localcontext


def allocate_order_discount(
    line_bases: Sequence[Decimal],
    order_discount: Decimal,
    quantum: Decimal = Decimal("1"),
) -> tuple[Decimal, ...]:
    """Allocate proportionally to post-line-discount bases; ties use line order."""
    if not quantum.is_finite() or quantum <= 0:
        raise ValueError("quantum must be finite and positive")
    if not order_discount.is_finite() or order_discount < 0:
        raise ValueError("order_discount must be finite and non-negative")
    if not line_bases:
        if order_discount == 0:
            return ()
        raise ValueError("cannot allocate a discount without sale items")
    if any(not value.is_finite() or value < 0 for value in line_bases):
        raise ValueError("line bases must be finite and non-negative")
    units = order_discount / quantum
    if units != units.to_integral_value():
        raise ValueError("order_discount must be a multiple of currency quantum")
    with localcontext() as context:
        # Keep the complete quota/remainder ranking at the same precision as
        # the basis sum; the caller's global Decimal context must not affect
        # which line receives a minor unit.
        context.prec = 60
        total_basis = sum(line_bases, Decimal("0"))
        if total_basis == 0:
            if order_discount == 0:
                return tuple(Decimal("0") for _ in line_bases)
            raise ValueError("cannot allocate a positive discount over zero-value items")
        if order_discount > total_basis:
            raise ValueError("order_discount cannot exceed total post-line-discount value")
        total_units = int(units)
        quotas = [Decimal(total_units) * basis / total_basis for basis in line_bases]
        floors = [int(quota.to_integral_value(rounding=ROUND_FLOOR)) for quota in quotas]
        remainder_units = total_units - sum(floors)
        order = sorted(range(len(quotas)), key=lambda i: (-(quotas[i] - floors[i]), i))
        for index in order[:remainder_units]:
            floors[index] += 1
        return tuple(Decimal(value) * quantum for value in floors)


def post_line_discount_basis(
    quantity: Decimal, unit_price: Decimal, line_discount: Decimal
) -> Decimal:
    """Return gross line value less its line-level discount."""
    if any(not value.is_finite() for value in (quantity, unit_price, line_discount)):
        raise ValueError("line values must be finite")
    if quantity <= 0 or unit_price < 0 or line_discount < 0:
        raise ValueError("quantity must be positive and prices/discounts non-negative")
    with localcontext() as context:
        context.prec = 60
        gross = quantity * unit_price
        if line_discount > gross:
            raise ValueError("line_discount cannot exceed gross line value")
        return gross - line_discount
