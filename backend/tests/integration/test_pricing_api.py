from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_engine
from app.main import app
from app.modules.identity.models import User
from app.modules.identity.security import hash_password
from app.modules.pricing.models import Calculation
from app.modules.tenancy.models import Membership, Role
from app.modules.tenancy.service import create_tenant

pytestmark = pytest.mark.integration
ORIGIN = "https://localhost:3000"
PASSWORD = "phase6 integration password"


def _new_client(role_name: str = "owner") -> tuple[TestClient, dict[str, str], int]:
    with Session(get_engine()) as db:
        user = User(
            email=f"phase6-{uuid.uuid4().hex}@example.test",
            password_hash=hash_password(PASSWORD),
            full_name="Phase 6 Integration",
            is_active=True,
        )
        db.add(user)
        db.flush()
        tenant, _ = create_tenant(db, user, "Phase 6 Test Tenant")
        if role_name != "owner":
            role = db.scalar(select(Role).where(Role.name == role_name))
            membership = db.scalar(
                select(Membership).where(
                    Membership.user_id == user.id, Membership.tenant_id == tenant.id
                )
            )
            assert role is not None and membership is not None
            membership.role_id = role.id
        tenant_id, user_email = tenant.id, user.email
        db.commit()

    client = TestClient(app, base_url=ORIGIN)
    login = client.post(
        "/api/v1/auth/login",
        headers={"Origin": ORIGIN},
        json={"email": user_email, "password": PASSWORD},
    )
    assert login.status_code == 200, login.text
    headers = {"Origin": ORIGIN, "X-CSRF-Token": login.headers["x-csrf-token"]}
    activated = client.post(f"/api/v1/tenants/{tenant_id}/activate", headers=headers)
    assert activated.status_code == 204, activated.text
    return client, headers, tenant_id


def test_order_profit_and_price_suggestion_are_journaled() -> None:
    client, headers, tenant_id = _new_client()
    try:
        product_response = client.post(
            "/api/v1/products",
            headers=headers,
            json={
                "sku": f"P6-{uuid.uuid4().hex[:10]}",
                "name": "Phase 6 product",
                "unit": "piece",
                "sale_price": "100.00",
                "purchase_cost": "55.00",
            },
        )
        assert product_response.status_code == 201, product_response.text
        product_id = product_response.json()["data"]["id"]
        order_response = client.post(
            "/api/v1/sales/orders",
            headers=headers,
            json={
                "order_number": f"P6-{uuid.uuid4().hex[:12]}",
                "order_date": "2026-11-20",
                "currency": "IRT",
                "order_discount": "10.00",
                "items": [
                    {
                        "product_id": product_id,
                        "quantity": "2.000",
                        "unit_price": "100.00",
                        "line_discount": "10.00",
                    }
                ],
            },
        )
        assert order_response.status_code == 201, order_response.text
        order_id = order_response.json()["data"]["id"]

        expense = client.post(
            "/api/v1/expenses",
            headers=headers,
            json={
                "expense_date": "2026-11-20",
                "type": "shipping",
                "amount": "20.00",
                "currency": "IRT",
                "allocation_scope": "order",
                "order_id": order_id,
            },
        )
        assert expense.status_code == 201, expense.text

        profit = client.get(f"/api/v1/sales/orders/{order_id}/profit")
        assert profit.status_code == 200, profit.text
        data = profit.json()["data"]
        assert data["formula_version"] == "FV-2"
        assert Decimal(data["revenue"]) == Decimal("180.00")
        assert Decimal(data["cogs"]) == Decimal("110.00")
        assert Decimal(data["net_operating_profit"]) == Decimal("50.00")
        assert data["calculation_id"] > 0

        payment = client.patch(
            f"/api/v1/sales/orders/{order_id}",
            headers=headers,
            json={"payment_status": "paid", "shipping_status": "shipped"},
        )
        assert payment.status_code == 200, payment.text
        item_id = order_response.json()["data"]["items"][0]["id"]
        returned = client.post(
            f"/api/v1/sales/orders/{order_id}/returns",
            headers={**headers, "Idempotency-Key": f"phase6-return-{uuid.uuid4().hex}"},
            json={
                "items": [
                    {
                        "sale_item_id": item_id,
                        "quantity": "1.000",
                        "refund_amount": "80.00",
                    }
                ]
            },
        )
        assert returned.status_code == 201, returned.text
        after_return = client.get(f"/api/v1/sales/orders/{order_id}/profit")
        assert after_return.status_code == 200, after_return.text
        returned_data = after_return.json()["data"]
        assert Decimal(returned_data["revenue"]) == Decimal("100")
        assert Decimal(returned_data["cogs"]) == Decimal("55")
        assert Decimal(returned_data["gross_profit"]) == Decimal("45")
        assert Decimal(returned_data["net_operating_profit"]) == Decimal("25")
        assert Decimal(returned_data["lines"][0]["return_variance"]) == Decimal("-10")

        cancelled_order = client.post(
            "/api/v1/sales/orders",
            headers=headers,
            json={
                "order_number": f"P6-CANCEL-{uuid.uuid4().hex[:10]}",
                "order_date": "2026-11-20",
                "currency": "IRT",
                "items": [
                    {
                        "product_id": product_id,
                        "quantity": "1.000",
                        "unit_price": "100.00",
                    }
                ],
            },
        )
        assert cancelled_order.status_code == 201, cancelled_order.text
        cancelled_id = cancelled_order.json()["data"]["id"]
        cancelled_status = client.post(
            f"/api/v1/sales/orders/{cancelled_id}/status-transition",
            headers=headers,
            json={"to": "cancelled"},
        )
        assert cancelled_status.status_code == 200, cancelled_status.text
        cancelled_expense = client.post(
            "/api/v1/expenses",
            headers=headers,
            json={
                "expense_date": "2026-11-20",
                "type": "shipping",
                "amount": "5.00",
                "currency": "IRT",
                "allocation_scope": "order",
                "order_id": cancelled_id,
            },
        )
        assert cancelled_expense.status_code == 201, cancelled_expense.text
        cancelled_profit = client.get(f"/api/v1/sales/orders/{cancelled_id}/profit")
        assert cancelled_profit.status_code == 200, cancelled_profit.text
        cancelled_data = cancelled_profit.json()["data"]
        assert Decimal(cancelled_data["revenue"]) == Decimal("0")
        assert Decimal(cancelled_data["unallocated_expenses"]) == Decimal("5")
        assert "ORDER_CANCELLED_COST_UNATTRIBUTED" in cancelled_data["warnings"]

        suggestion = client.post(
            "/api/v1/pricing/suggest",
            headers=headers,
            json={"product_id": product_id, "target_margin": "0.25"},
        )
        assert suggestion.status_code == 200, suggestion.text
        suggested = suggestion.json()["data"]
        assert suggested["suggested_price"] == "73"
        assert suggested["formula_version"] == "FV-2"

        manual_suggestion = client.post(
            "/api/v1/pricing/suggest",
            headers=headers,
            json={"cost": "100.00", "target_margin": "0.25"},
        )
        assert manual_suggestion.status_code == 200, manual_suggestion.text
        assert manual_suggestion.json()["data"]["suggested_price"] == "133"

        rejected = client.post(
            "/api/v1/pricing/suggest",
            headers=headers,
            json={"cost": "100", "target_margin": "0.25", "include_fees": True},
        )
        assert rejected.status_code == 422
        assert rejected.json()["error"]["code"] == "INCLUDE_FEES_POLICY_UNDEFINED"

        with Session(get_engine()) as db:
            records = db.scalars(
                select(Calculation).where(Calculation.tenant_id == tenant_id)
            ).all()
            assert {record.calc_type for record in records} == {"order", "price_suggestion"}
            assert all(len(record.input_hash) == 64 for record in records)
            assert sum(record.calc_type == "order" for record in records) == 3
            assert any(
                record.input.get("returns") for record in records if record.calc_type == "order"
            )
            assert {record.source for record in records} == {"system", "manual"}
            assert all(record.formula_version == "FV-2" for record in records)
            product_calculation = Calculation(
                tenant_id=tenant_id,
                calc_type="product",
                formula_version="FV-2",
                input={"product_id": product_id},
                output={"net_profit": "10"},
                warnings=[],
                input_hash="a" * 64,
                source="report",
            )
            db.add(product_calculation)
            db.commit()
            assert product_calculation.id is not None
    finally:
        client.close()


def test_analytics_endpoints_share_fv2_and_scope_expenses() -> None:
    client, headers, _ = _new_client()
    try:
        today = date.today().isoformat()
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        product = client.post(
            "/api/v1/products",
            headers=headers,
            json={
                "sku": f"AN-{uuid.uuid4().hex[:10]}",
                "name": "Analytics item",
                "unit": "piece",
                "sale_price": "100",
                "purchase_cost": "55",
            },
        )
        assert product.status_code == 201, product.text
        product_id = product.json()["data"]["id"]
        order = client.post(
            "/api/v1/sales/orders",
            headers=headers,
            json={
                "order_number": f"AN-{uuid.uuid4().hex[:10]}",
                "order_date": today,
                "currency": "IRT",
                "items": [{"product_id": product_id, "quantity": "2.000", "unit_price": "100.00"}],
            },
        )
        assert order.status_code == 201, order.text
        order_id = order.json()["data"]["id"]
        for state in ("confirmed", "processing", "completed"):
            transitioned = client.post(
                f"/api/v1/sales/orders/{order_id}/status-transition",
                headers=headers,
                json={"to": state},
            )
            assert transitioned.status_code == 200, transitioned.text

        for scope, amount, extra in (
            ("order", "10.00", {"order_id": order_id}),
            (
                "period",
                "5.00",
                {
                    "period_start": today,
                    "period_end": today,
                    "allocation_strategy": "revenue_share",
                },
            ),
            ("product", "3.00", {"product_id": product_id}),
        ):
            expense = client.post(
                "/api/v1/expenses",
                headers=headers,
                json={
                    "expense_date": today,
                    "type": "operational",
                    "amount": amount,
                    "currency": "IRT",
                    "allocation_scope": scope,
                    **extra,
                },
            )
            assert expense.status_code == 201, expense.text

        prorated_expense = client.post(
            "/api/v1/expenses",
            headers=headers,
            json={
                "expense_date": today,
                "type": "operational",
                "amount": "1.00",
                "currency": "IRT",
                "allocation_scope": "period",
                "period_start": today,
                "period_end": tomorrow,
                "allocation_strategy": "revenue_share",
            },
        )
        assert prorated_expense.status_code == 201, prorated_expense.text
        query = f"date_from={today}&date_to={today}"
        summary = client.get(f"/api/v1/analytics/summary?{query}")
        assert summary.status_code == 200, summary.text
        data = summary.json()["data"]
        assert Decimal(data["revenue"]) == Decimal("200")
        assert Decimal(data["cogs"]) == Decimal("110")
        assert Decimal(data["expenses"]) == Decimal("16")
        assert Decimal(data["net_profit"]) == Decimal("74")
        assert data["formula_version"] == "FV-2"
        assert data["calculation_id"] > 0

        products = client.get(f"/api/v1/analytics/products?{query}")
        assert products.status_code == 200, products.text
        product_rows = products.json()["data"]["products"]
        assert len(product_rows) == 1
        assert Decimal(product_rows[0]["net_profit"]) == Decimal("71")
        assert Decimal(product_rows[0]["direct_product_expenses"]) == Decimal("3")
        assert Decimal(product_rows[0]["allocated_period_expenses"]) == Decimal("6")

        trends = client.get(f"/api/v1/analytics/trends?{query}&group_by=day")
        assert trends.status_code == 200, trends.text
        assert Decimal(trends.json()["data"]["items"][0]["revenue"]) == Decimal("200")

        expenses = client.get(f"/api/v1/analytics/expenses?{query}")
        assert expenses.status_code == 200, expenses.text
        expense_data = expenses.json()["data"]
        assert Decimal(expense_data["total_in_period_profit"]) == Decimal("16")
        assert Decimal(expense_data["product_scoped_excluded"]) == Decimal("3")
        prior_order = client.post(
            "/api/v1/sales/orders",
            headers=headers,
            json={
                "order_number": f"AN-OLD-{uuid.uuid4().hex[:10]}",
                "order_date": yesterday,
                "currency": "IRT",
                "items": [{"product_id": product_id, "quantity": "1.000", "unit_price": "100.00"}],
            },
        )
        assert prior_order.status_code == 201, prior_order.text
        prior_id = prior_order.json()["data"]["id"]
        paid_shipped = client.patch(
            f"/api/v1/sales/orders/{prior_id}",
            headers=headers,
            json={"payment_status": "paid", "shipping_status": "shipped"},
        )
        assert paid_shipped.status_code == 200, paid_shipped.text
        for state in ("confirmed", "processing", "completed"):
            transitioned = client.post(
                f"/api/v1/sales/orders/{prior_id}/status-transition",
                headers=headers,
                json={"to": state},
            )
            assert transitioned.status_code == 200, transitioned.text
        prior_item_id = prior_order.json()["data"]["items"][0]["id"]
        returned = client.post(
            f"/api/v1/sales/orders/{prior_id}/returns",
            headers={**headers, "Idempotency-Key": f"analytics-return-{uuid.uuid4().hex}"},
            json={
                "items": [
                    {"sale_item_id": prior_item_id, "quantity": "1.000", "refund_amount": "80.00"}
                ]
            },
        )
        assert returned.status_code == 201, returned.text
        prior_period = client.get(
            f"/api/v1/analytics/summary?date_from={yesterday}&date_to={yesterday}"
        )
        assert prior_period.status_code == 200, prior_period.text
        assert Decimal(prior_period.json()["data"]["revenue"]) == Decimal("100")
        assert Decimal(prior_period.json()["data"]["cogs"]) == Decimal("55")
        same_day_order = client.post(
            "/api/v1/sales/orders",
            headers=headers,
            json={
                "order_number": f"AN-SAME-{uuid.uuid4().hex[:10]}",
                "order_date": today,
                "currency": "IRT",
                "items": [{"product_id": product_id, "quantity": "1.000", "unit_price": "100.00"}],
            },
        )
        assert same_day_order.status_code == 201, same_day_order.text
        same_day_id = same_day_order.json()["data"]["id"]
        shipped = client.patch(
            f"/api/v1/sales/orders/{same_day_id}",
            headers=headers,
            json={"payment_status": "paid", "shipping_status": "shipped"},
        )
        assert shipped.status_code == 200, shipped.text
        for state in ("confirmed", "processing", "completed"):
            transitioned = client.post(
                f"/api/v1/sales/orders/{same_day_id}/status-transition",
                headers=headers,
                json={"to": state},
            )
            assert transitioned.status_code == 200, transitioned.text
        same_day_item_id = same_day_order.json()["data"]["items"][0]["id"]
        same_day_return = client.post(
            f"/api/v1/sales/orders/{same_day_id}/returns",
            headers={**headers, "Idempotency-Key": f"analytics-same-day-{uuid.uuid4().hex}"},
            json={
                "items": [
                    {
                        "sale_item_id": same_day_item_id,
                        "quantity": "1.000",
                        "refund_amount": "80.00",
                    }
                ]
            },
        )
        assert same_day_return.status_code == 201, same_day_return.text
        return_period = client.get(f"/api/v1/analytics/summary?date_from={today}&date_to={today}")
        assert return_period.status_code == 200, return_period.text
        assert Decimal(return_period.json()["data"]["revenue"]) == Decimal("140")
        assert Decimal(return_period.json()["data"]["cogs"]) == Decimal("55")
        fractional_order = client.post(
            "/api/v1/sales/orders",
            headers=headers,
            json={
                "order_number": f"AN-FRACTION-{uuid.uuid4().hex[:10]}",
                "order_date": today,
                "currency": "IRT",
                "items": [{"product_id": product_id, "quantity": "1.250", "unit_price": "100.00"}],
            },
        )
        assert fractional_order.status_code == 201, fractional_order.text
        fractional_id = fractional_order.json()["data"]["id"]
        fractional_paid = client.patch(
            f"/api/v1/sales/orders/{fractional_id}",
            headers=headers,
            json={"payment_status": "paid", "shipping_status": "shipped"},
        )
        assert fractional_paid.status_code == 200, fractional_paid.text
        for state in ("confirmed", "processing", "completed"):
            transitioned = client.post(
                f"/api/v1/sales/orders/{fractional_id}/status-transition",
                headers=headers,
                json={"to": state},
            )
            assert transitioned.status_code == 200, transitioned.text
        fractional_item_id = fractional_order.json()["data"]["items"][0]["id"]
        fractional_return = client.post(
            f"/api/v1/sales/orders/{fractional_id}/returns",
            headers={**headers, "Idempotency-Key": f"analytics-fraction-{uuid.uuid4().hex}"},
            json={
                "items": [
                    {
                        "sale_item_id": fractional_item_id,
                        "quantity": "0.250",
                        "refund_amount": "25.00",
                    }
                ]
            },
        )
        assert fractional_return.status_code == 201, fractional_return.text
        fractional_summary = client.get(
            f"/api/v1/analytics/summary?date_from={today}&date_to={today}"
        )
        assert fractional_summary.status_code == 200, fractional_summary.text
        assert Decimal(fractional_summary.json()["data"]["units_sold"]) == Decimal("4.250")
        assert Decimal(fractional_summary.json()["data"]["returned_units"]) == Decimal("2.250")
        fractional_products = client.get(
            f"/api/v1/analytics/products?date_from={today}&date_to={today}"
        )
        assert fractional_products.status_code == 200, fractional_products.text
        fractional_product = fractional_products.json()["data"]["products"][0]
        assert Decimal(fractional_product["units_sold"]) == Decimal("4.250")
        assert Decimal(fractional_product["returned_units"]) == Decimal("2.250")
    finally:
        client.close()


def test_analytics_xlsx_export_contains_all_report_sheets() -> None:
    client, headers, _tenant_id = _new_client()
    try:
        response = client.get(
            "/api/v1/analytics/export.xlsx?date_from=2026-11-01&date_to=2026-11-21&group_by=day",
            headers=headers,
        )
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        assert (
            "marginpilot-analytics-2026-11-01-2026-11-21.xlsx"
            in response.headers["content-disposition"]
        )
        workbook = load_workbook(BytesIO(response.content), read_only=True, data_only=True)
        assert workbook.sheetnames == ["Summary", "Products", "Trends", "Expenses", "Warnings"]
        summary_rows = list(workbook["Summary"].iter_rows(values_only=True))
        assert summary_rows[0] == ("Metric", "Value", "Currency")
        assert ("Formula version", "FV-2", None) in summary_rows
        assert list(workbook["Products"].iter_rows(values_only=True))[0][0] == "Product ID"
        assert list(workbook["Trends"].iter_rows(values_only=True))[0][0] == "Period"
        assert list(workbook["Expenses"].iter_rows(values_only=True))[0][0] == "Type"
        workbook.close()
    finally:
        client.close()
