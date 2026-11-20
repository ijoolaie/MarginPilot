from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.modules.expenses.router import ExpenseCreate


def test_order_expense_requires_only_order_reference() -> None:
    payload = ExpenseCreate(
        expense_date=date(2026, 11, 20),
        type="shipping",
        amount=Decimal("120"),
        currency="IRT",
        allocation_scope="order",
        order_id=3,
    )
    assert payload.order_id == 3
    assert payload.product_id is None


def test_period_expense_requires_ordered_date_range() -> None:
    with pytest.raises(ValidationError):
        ExpenseCreate(
            expense_date=date(2026, 11, 20),
            type="operational",
            amount=Decimal("120"),
            currency="IRT",
            allocation_scope="period",
            period_start=date(2026, 11, 21),
            period_end=date(2026, 11, 20),
        )


def test_product_expense_rejects_conflicting_targets() -> None:
    with pytest.raises(ValidationError):
        ExpenseCreate(
            expense_date=date(2026, 11, 20),
            type="packaging",
            amount=Decimal("120"),
            currency="IRT",
            allocation_scope="product",
            product_id=4,
            order_id=3,
        )
