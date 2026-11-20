from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.modules.sales.router import (
    SaleItemUpdate,
    SaleLineInput,
    SalesOrderCreate,
    SalesOrderTransition,
    SalesOrderUpdate,
    SalesRefundCreate,
    SalesReturnCreate,
)


def test_manual_sale_line_requires_sku_and_name() -> None:
    with pytest.raises(ValidationError):
        SaleLineInput(quantity=1, unit_price=100)


def test_variant_requires_product() -> None:
    with pytest.raises(ValidationError):
        SaleLineInput(variant_id=7, sku="SKU-7", name="Item", quantity=1, unit_price=100)


def test_product_sale_line_uses_product_snapshot_not_client_names() -> None:
    with pytest.raises(ValidationError):
        SaleLineInput(product_id=7, sku="tampered", quantity=1, unit_price=100)


def test_valid_manual_sale_order() -> None:
    payload = SalesOrderCreate(
        order_number="  SO-001  ",
        order_date=date(2026, 11, 20),
        currency="IRT",
        items=[
            SaleLineInput(
                sku="SKU-1",
                name="Item 1",
                quantity=Decimal("2"),
                unit_price=Decimal("1000"),
                line_discount=Decimal("100"),
            )
        ],
        order_discount=Decimal("100"),
    )
    assert payload.order_number == "SO-001"
    assert payload.items[0].line_discount == Decimal("100")


def test_sales_order_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        SalesOrderCreate(
            order_number="SO-002",
            order_date=date(2026, 11, 20),
            currency="IRT",
            items=[{"sku": "A", "name": "A", "quantity": 1, "unit_price": 10}],
            surprise="not allowed",
        )


def test_return_rejects_duplicate_sale_item_ids() -> None:
    with pytest.raises(ValidationError):
        SalesReturnCreate(
            items=[
                {"sale_item_id": 1, "quantity": "1", "refund_amount": "100"},
                {"sale_item_id": 1, "quantity": "1", "refund_amount": "100"},
            ]
        )


def test_return_schema_accepts_partial_return_and_actual_refund() -> None:
    payload = SalesReturnCreate(
        items=[{"sale_item_id": 2, "quantity": "0.500", "refund_amount": "75.00"}]
    )
    assert payload.items[0].quantity == Decimal("0.500")
    assert payload.items[0].refund_amount == Decimal("75.00")


def test_order_transition_only_accepts_documented_destinations() -> None:
    assert SalesOrderTransition(to="confirmed").to == "confirmed"
    with pytest.raises(ValidationError):
        SalesOrderTransition(to="returned")


def test_sale_item_update_rejects_negative_quantity() -> None:
    with pytest.raises(ValidationError):
        SaleItemUpdate(quantity=Decimal("-1"))


def test_order_update_schema_rejects_refund_state_direct_write() -> None:
    with pytest.raises(ValidationError):
        SalesOrderUpdate(payment_status="refunded")


def test_independent_refund_requires_positive_amount_and_cleans_notes() -> None:
    payload = SalesRefundCreate(amount=Decimal("25.00"), notes="  cancellation  ")
    assert payload.amount == Decimal("25.00")
    assert payload.notes == "cancellation"
    with pytest.raises(ValidationError):
        SalesRefundCreate(amount=Decimal("0"))
