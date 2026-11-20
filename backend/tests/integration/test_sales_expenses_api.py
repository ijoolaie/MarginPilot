from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.core.db import get_engine
from app.main import app
from app.modules.audit.models import AuditLog
from app.modules.expenses.models import Expense
from app.modules.identity.models import User
from app.modules.identity.security import hash_password
from app.modules.sales.models import SaleItem, SalesOrder, SalesRefund, SalesReturn, SalesReturnItem
from app.modules.tenancy.models import Membership, Role
from app.modules.tenancy.service import create_tenant

pytestmark = pytest.mark.integration
ORIGIN = "https://localhost:3000"
PASSWORD = "correct horse battery staple 2026"


def _seed_user(role_name: str = "owner") -> tuple[User, int]:
    with OrmSession(get_engine()) as db:
        user = User(
            email=f"phase5-{uuid.uuid4().hex}@example.test",
            password_hash=hash_password(PASSWORD),
            full_name="Phase 5 Integration User",
            is_active=True,
        )
        db.add(user)
        db.flush()
        tenant, _ = create_tenant(db, user, "Phase 5 Integration Workspace")
        if role_name != "owner":
            role = db.scalar(select(Role).where(Role.name == role_name))
            membership = db.scalar(
                select(Membership).where(
                    Membership.user_id == user.id, Membership.tenant_id == tenant.id
                )
            )
            assert role is not None and membership is not None
            membership.role_id = role.id
        db.commit()
        db.refresh(user)
        return user, tenant.id


def _client_for(user: User, tenant_id: int) -> tuple[TestClient, dict[str, str]]:
    client = TestClient(app, base_url=ORIGIN)
    login = client.post(
        "/api/v1/auth/login",
        headers={"Origin": ORIGIN},
        json={"email": user.email, "password": PASSWORD},
    )
    assert login.status_code == 200, login.text
    headers = {"Origin": ORIGIN, "X-CSRF-Token": login.headers["x-csrf-token"]}
    activated = client.post(f"/api/v1/tenants/{tenant_id}/activate", headers=headers)
    assert activated.status_code == 204, activated.text
    return client, headers


def _create_product(client: TestClient, headers: dict[str, str], sku: str) -> int:
    response = client.post(
        "/api/v1/products",
        headers=headers,
        json={
            "sku": sku,
            "name": "Phase 5 Test Product",
            "unit": "piece",
            "sale_price": "100.00",
            "purchase_cost": "55.00",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


def _create_order(
    client: TestClient, headers: dict[str, str], product_id: int, order_number: str
) -> dict[str, object]:
    response = client.post(
        "/api/v1/sales/orders",
        headers=headers,
        json={
            "order_number": order_number,
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
    assert response.status_code == 201, response.text
    return response.json()["data"]


def test_sales_order_returns_and_idempotency_are_transactional() -> None:
    user, tenant_id = _seed_user()
    client, headers = _client_for(user, tenant_id)
    try:
        product_id = _create_product(client, headers, f"P5-{uuid.uuid4().hex[:10]}")
        order = _create_order(client, headers, product_id, f"P5-ORDER-{uuid.uuid4().hex[:10]}")
        order_id = int(order["id"])
        item_id = int(order["items"][0]["id"])
        assert order["items"][0]["unit_cost"] == "55.00"
        assert order["items"][0]["cost_source"] == "product_current"
        assert order["items"][0]["order_discount_share"] == "10.00"
        assert Decimal(str(order["net_total"])) == Decimal("180.00")
        assert client.get(f"/api/v1/sales/orders/{order_id}").status_code == 200
        changed = client.patch(
            f"/api/v1/sales/orders/{order_id}/items/{item_id}",
            headers=headers,
            json={"unit_price": "110.00"},
        )
        assert changed.status_code == 200, changed.text
        for next_status in ("confirmed", "processing", "completed"):
            transitioned = client.post(
                f"/api/v1/sales/orders/{order_id}/status-transition",
                headers=headers,
                json={"to": next_status},
            )
            assert transitioned.status_code == 200, transitioned.text
        immutable = client.patch(
            f"/api/v1/sales/orders/{order_id}/items/{item_id}",
            headers=headers,
            json={"unit_price": "120.00"},
        )
        assert immutable.status_code == 409

        second = _create_order(client, headers, product_id, f"P5-ORDER-{uuid.uuid4().hex[:10]}")
        second_id = int(second["id"])
        second_item_id = int(second["items"][0]["id"])
        payment = client.patch(
            f"/api/v1/sales/orders/{second_id}",
            headers=headers,
            json={"payment_status": "paid", "shipping_status": "shipped"},
        )
        assert payment.status_code == 200, payment.text
        return_payload = {
            "items": [
                {"sale_item_id": second_item_id, "quantity": "1.000", "refund_amount": "80.00"}
            ],
            "notes": "Partial return",
        }
        idem_headers = {**headers, "Idempotency-Key": f"return-{uuid.uuid4().hex}"}
        returned = client.post(
            f"/api/v1/sales/orders/{second_id}/returns", headers=idem_headers, json=return_payload
        )
        assert returned.status_code == 201, returned.text
        return_id = returned.json()["data"]["id"]
        replay = client.post(
            f"/api/v1/sales/orders/{second_id}/returns", headers=idem_headers, json=return_payload
        )
        assert replay.status_code == 201, replay.text
        assert replay.json()["data"]["id"] == return_id
        conflict = client.post(
            f"/api/v1/sales/orders/{second_id}/returns",
            headers=idem_headers,
            json={
                "items": [
                    {"sale_item_id": second_item_id, "quantity": "1.000", "refund_amount": "81.00"}
                ]
            },
        )
        assert conflict.status_code == 409
        second_return = client.post(
            f"/api/v1/sales/orders/{second_id}/returns",
            headers={**headers, "Idempotency-Key": f"return-{uuid.uuid4().hex}"},
            json={
                "items": [
                    {"sale_item_id": second_item_id, "quantity": "1.000", "refund_amount": "100.00"}
                ]
            },
        )
        assert second_return.status_code == 201, second_return.text
        payment_reset = client.patch(
            f"/api/v1/sales/orders/{second_id}",
            headers=headers,
            json={"payment_status": "paid"},
        )
        assert payment_reset.status_code == 409
        assert payment_reset.json()["error"]["code"] == "PAYMENT_STATE_INVALID"
        history = client.get(f"/api/v1/sales/orders/{second_id}/returns")
        assert history.status_code == 200 and len(history.json()["data"]) == 2
        with OrmSession(get_engine()) as db:
            persisted_item = db.get(SaleItem, second_item_id)
            persisted_order = db.get(SalesOrder, second_id)
            assert persisted_item is not None and persisted_order is not None
            assert str(persisted_item.returned_quantity) == "2.000"
            assert str(persisted_item.refund_amount) == "180.00"
            assert persisted_order.payment_status == "refunded"
            assert persisted_order.shipping_status == "returned"
            returns = db.scalars(
                select(SalesReturn).where(
                    SalesReturn.tenant_id == tenant_id, SalesReturn.order_id == second_id
                )
            ).all()
            assert len(returns) == 2
            return_items = db.scalars(
                select(SalesReturnItem).where(SalesReturnItem.tenant_id == tenant_id)
            ).all()
            assert len(return_items) == 2
            events = db.scalars(
                select(AuditLog).where(
                    AuditLog.tenant_id == tenant_id,
                    AuditLog.entity_type.in_(["sales_order", "sales_return"]),
                )
            ).all()
            assert len(events) >= 6
    finally:
        client.close()


def test_expense_crud_validates_scope_and_soft_deletes() -> None:
    user, tenant_id = _seed_user()
    client, headers = _client_for(user, tenant_id)
    try:
        product_id = _create_product(client, headers, f"EXP-{uuid.uuid4().hex[:10]}")
        order = _create_order(client, headers, product_id, f"EXP-ORDER-{uuid.uuid4().hex[:10]}")
        order_id = int(order["id"])
        created = client.post(
            "/api/v1/expenses",
            headers=headers,
            json={
                "expense_date": "2026-11-20",
                "type": "packaging",
                "amount": "2500.00",
                "currency": "IRT",
                "allocation_scope": "product",
                "product_id": product_id,
                "allocation_strategy": "equal_quantity",
            },
        )
        assert created.status_code == 201, created.text
        expense_id = created.json()["data"]["id"]
        order_expense = client.post(
            "/api/v1/expenses",
            headers=headers,
            json={
                "expense_date": "2026-11-20",
                "type": "shipping",
                "amount": "1200.00",
                "currency": "IRT",
                "allocation_scope": "order",
                "order_id": order_id,
            },
        )
        assert order_expense.status_code == 201, order_expense.text
        period_expense = client.post(
            "/api/v1/expenses",
            headers=headers,
            json={
                "expense_date": "2026-11-20",
                "type": "operational",
                "amount": "9000.00",
                "currency": "IRT",
                "allocation_scope": "period",
                "period_start": "2026-11-01",
                "period_end": "2026-11-30",
                "allocation_strategy": "revenue_share",
            },
        )
        assert period_expense.status_code == 201, period_expense.text
        invalid_scope = client.post(
            "/api/v1/expenses",
            headers=headers,
            json={
                "expense_date": "2026-11-20",
                "type": "other",
                "amount": "10.00",
                "currency": "IRT",
                "allocation_scope": "order",
                "product_id": product_id,
            },
        )
        assert invalid_scope.status_code == 422
        wrong_currency = client.post(
            "/api/v1/expenses",
            headers=headers,
            json={
                "expense_date": "2026-11-20",
                "type": "other",
                "amount": "10.00",
                "currency": "IRR",
                "allocation_scope": "product",
                "product_id": product_id,
            },
        )
        assert wrong_currency.status_code == 422
        updated = client.patch(
            f"/api/v1/expenses/{expense_id}",
            headers=headers,
            json={"amount": "2750.00", "description": " Updated packaging cost "},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["data"]["amount"] == "2750.00"
        assert updated.json()["data"]["description"] == "Updated packaging cost"
        listed = client.get("/api/v1/expenses?type=packaging&allocation_scope=product")
        assert listed.status_code == 200 and listed.json()["pagination"]["total"] == 1
        assert client.delete(f"/api/v1/expenses/{expense_id}", headers=headers).status_code == 204
        assert client.get(f"/api/v1/expenses/{expense_id}").status_code == 404
        with OrmSession(get_engine()) as db:
            persisted = db.get(Expense, expense_id)
            assert persisted is not None and persisted.deleted_at is not None
            audit = db.scalars(
                select(AuditLog).where(
                    AuditLog.tenant_id == tenant_id, AuditLog.entity_type == "expense"
                )
            ).all()
            assert len(audit) >= 4
    finally:
        client.close()


def test_sales_and_expenses_enforce_tenant_scope_and_rbac() -> None:
    owner, owner_tenant_id = _seed_user()
    owner_client, owner_headers = _client_for(owner, owner_tenant_id)
    foreign_owner, foreign_tenant_id = _seed_user()
    foreign_client, foreign_headers = _client_for(foreign_owner, foreign_tenant_id)
    analyst, analyst_tenant_id = _seed_user("analyst")
    analyst_client, analyst_headers = _client_for(analyst, analyst_tenant_id)
    try:
        product_id = _create_product(owner_client, owner_headers, f"ISO-{uuid.uuid4().hex[:10]}")
        order = _create_order(
            owner_client, owner_headers, product_id, f"ISO-ORDER-{uuid.uuid4().hex[:10]}"
        )
        order_id = int(order["id"])
        assert foreign_client.get(f"/api/v1/sales/orders/{order_id}").status_code == 404
        foreign_expense = foreign_client.post(
            "/api/v1/expenses",
            headers=foreign_headers,
            json={
                "expense_date": "2026-11-20",
                "type": "shipping",
                "amount": "100.00",
                "currency": "IRT",
                "allocation_scope": "order",
                "order_id": order_id,
            },
        )
        assert foreign_expense.status_code == 404
        assert analyst_client.get("/api/v1/sales/orders").status_code == 200
        write_denied = analyst_client.post(
            "/api/v1/sales/orders",
            headers=analyst_headers,
            json={
                "order_number": f"ANALYST-{uuid.uuid4().hex[:10]}",
                "order_date": "2026-11-20",
                "currency": "IRT",
                "items": [
                    {"sku": "MANUAL-1", "name": "Manual item", "quantity": "1", "unit_price": "100"}
                ],
            },
        )
        assert write_denied.status_code == 403
    finally:
        owner_client.close()
        foreign_client.close()
        analyst_client.close()


def test_cancelled_paid_order_uses_separate_refund_ledger() -> None:
    user, tenant_id = _seed_user()
    client, headers = _client_for(user, tenant_id)
    try:
        product_id = _create_product(client, headers, f"RF-{uuid.uuid4().hex[:10]}")
        order = _create_order(client, headers, product_id, f"RF-ORDER-{uuid.uuid4().hex[:10]}")
        order_id = int(order["id"])
        item_id = int(order["items"][0]["id"])
        paid = client.patch(
            f"/api/v1/sales/orders/{order_id}", headers=headers, json={"payment_status": "paid"}
        )
        assert paid.status_code == 200, paid.text
        premature_return = client.post(
            f"/api/v1/sales/orders/{order_id}/returns",
            headers={**headers, "Idempotency-Key": f"return-{uuid.uuid4().hex}"},
            json={"items": [{"sale_item_id": item_id, "quantity": "1", "refund_amount": "1"}]},
        )
        assert premature_return.status_code == 409
        assert premature_return.json()["error"]["code"] == "ORDER_NOT_SHIPPED"
        immutable = client.patch(
            f"/api/v1/sales/orders/{order_id}/items/{item_id}",
            headers=headers,
            json={"unit_price": "90"},
        )
        assert immutable.status_code == 409
        cancelled = client.post(
            f"/api/v1/sales/orders/{order_id}/status-transition",
            headers=headers,
            json={"to": "cancelled"},
        )
        assert cancelled.status_code == 200, cancelled.text
        payload = {"amount": "60.00", "notes": "Cancellation refund"}
        idem = {**headers, "Idempotency-Key": f"refund-{uuid.uuid4().hex}"}
        first = client.post(f"/api/v1/sales/orders/{order_id}/refunds", headers=idem, json=payload)
        assert first.status_code == 201, first.text
        replay = client.post(f"/api/v1/sales/orders/{order_id}/refunds", headers=idem, json=payload)
        assert replay.status_code == 201
        assert replay.json()["data"]["id"] == first.json()["data"]["id"]
        second = client.post(
            f"/api/v1/sales/orders/{order_id}/refunds",
            headers={**headers, "Idempotency-Key": f"refund-{uuid.uuid4().hex}"},
            json={"amount": "120.00"},
        )
        assert second.status_code == 201, second.text
        over = client.post(
            f"/api/v1/sales/orders/{order_id}/refunds",
            headers={**headers, "Idempotency-Key": f"refund-{uuid.uuid4().hex}"},
            json={"amount": "0.01"},
        )
        assert (
            over.status_code == 409
            and over.json()["error"]["code"] == "REFUND_EXCEEDS_AMOUNT_RECEIVED"
        )
        physical_return = client.post(
            f"/api/v1/sales/orders/{order_id}/returns",
            headers={**headers, "Idempotency-Key": f"return-{uuid.uuid4().hex}"},
            json={"items": [{"sale_item_id": item_id, "quantity": "1", "refund_amount": "1"}]},
        )
        assert (
            physical_return.status_code == 409
            and physical_return.json()["error"]["code"] == "ORDER_CANCELLED"
        )
        history = client.get(f"/api/v1/sales/orders/{order_id}/refunds")
        assert history.status_code == 200 and len(history.json()["data"]) == 2
        with OrmSession(get_engine()) as db:
            persisted = db.get(SalesOrder, order_id)
            refunds = db.scalars(
                select(SalesRefund).where(
                    SalesRefund.tenant_id == tenant_id, SalesRefund.order_id == order_id
                )
            ).all()
            returns = db.scalars(
                select(SalesReturn).where(
                    SalesReturn.tenant_id == tenant_id, SalesReturn.order_id == order_id
                )
            ).all()
            assert (
                persisted is not None
                and persisted.status == "cancelled"
                and persisted.payment_status == "refunded"
            )
            assert len(refunds) == 2 and len(returns) == 0
            events = db.scalars(
                select(AuditLog).where(
                    AuditLog.tenant_id == tenant_id, AuditLog.entity_type == "sales_refund"
                )
            ).all()
            assert len(events) == 2

        other_user, other_tenant_id = _seed_user()
        other_client, other_headers = _client_for(other_user, other_tenant_id)
        try:
            hidden_history = other_client.get(f"/api/v1/sales/orders/{order_id}/refunds")
            assert hidden_history.status_code == 404
            hidden_refund = other_client.post(
                f"/api/v1/sales/orders/{order_id}/refunds",
                headers={**other_headers, "Idempotency-Key": f"cross-tenant-{uuid.uuid4().hex}"},
                json={"amount": "1.00"},
            )
            assert hidden_refund.status_code == 404
        finally:
            other_client.close()

        shipped = _create_order(client, headers, product_id, f"RF-SHIPPED-{uuid.uuid4().hex[:10]}")
        shipped_id = int(shipped["id"])
        marked_shipped = client.patch(
            f"/api/v1/sales/orders/{shipped_id}",
            headers=headers,
            json={"payment_status": "paid", "shipping_status": "shipped"},
        )
        assert marked_shipped.status_code == 200, marked_shipped.text
        cannot_cancel = client.post(
            f"/api/v1/sales/orders/{shipped_id}/status-transition",
            headers=headers,
            json={"to": "cancelled"},
        )
        assert (
            cannot_cancel.status_code == 409
            and cannot_cancel.json()["error"]["code"] == "ORDER_ALREADY_SHIPPED_USE_RETURN"
        )
    finally:
        client.close()


def test_physical_return_cannot_refund_more_than_received_total() -> None:
    user, tenant_id = _seed_user()
    client, headers = _client_for(user, tenant_id)
    try:
        product_id = _create_product(client, headers, f"CAP-{uuid.uuid4().hex[:10]}")
        order = _create_order(client, headers, product_id, f"CAP-ORDER-{uuid.uuid4().hex[:10]}")
        order_id = int(order["id"])
        item_id = int(order["items"][0]["id"])
        paid = client.patch(
            f"/api/v1/sales/orders/{order_id}",
            headers=headers,
            json={"payment_status": "paid", "shipping_status": "shipped"},
        )
        assert paid.status_code == 200, paid.text
        rejected = client.post(
            f"/api/v1/sales/orders/{order_id}/returns",
            headers={**headers, "Idempotency-Key": f"return-{uuid.uuid4().hex}"},
            json={"items": [{"sale_item_id": item_id, "quantity": "1", "refund_amount": "180.01"}]},
        )
        assert rejected.status_code == 409
        assert rejected.json()["error"]["code"] == "REFUND_EXCEEDS_AMOUNT_RECEIVED"
        history = client.get(f"/api/v1/sales/orders/{order_id}/returns")
        assert history.status_code == 200 and history.json()["data"] == []
        with OrmSession(get_engine()) as db:
            persisted = db.get(SalesOrder, order_id)
            assert persisted is not None and persisted.payment_status == "paid"
    finally:
        client.close()
