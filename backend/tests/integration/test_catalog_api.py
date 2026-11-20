from __future__ import annotations

import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.core.db import get_engine
from app.main import app
from app.modules.audit.models import AuditLog
from app.modules.catalog.models import ProductPriceHistory, SupplierPriceList
from app.modules.identity.models import User
from app.modules.identity.security import hash_password
from app.modules.tenancy.models import Membership, Role
from app.modules.tenancy.service import create_tenant

pytestmark = pytest.mark.integration
ORIGIN = "http://localhost:3000"
PASSWORD = "correct horse battery staple 2026"


def _seed_user(role_name: str = "owner") -> tuple[User, int]:
    with OrmSession(get_engine()) as db:
        user = User(
            email=f"catalog-{uuid.uuid4().hex}@example.test",
            password_hash=hash_password(PASSWORD),
            full_name="Catalog Test User",
            is_active=True,
        )
        db.add(user)
        db.flush()
        tenant, _ = create_tenant(db, user, "Catalog Test Workspace")
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


def test_catalog_categories_products_variants_and_price_history() -> None:
    user, tenant_id = _seed_user()
    client, headers = _client_for(user, tenant_id)
    try:
        root = client.post("/api/v1/categories", headers=headers, json={"name": "Packaging"})
        assert root.status_code == 201, root.text
        root_id = root.json()["data"]["id"]
        child = client.post(
            "/api/v1/categories", headers=headers, json={"name": "Boxes", "parent_id": root_id}
        )
        assert child.status_code == 201, child.text
        child_id = child.json()["data"]["id"]
        cycle = client.patch(
            f"/api/v1/categories/{root_id}", headers=headers, json={"parent_id": child_id}
        )
        assert cycle.status_code == 409
        assert cycle.json()["error"]["code"] == "CATEGORY_CYCLE"

        created = client.post(
            "/api/v1/products",
            headers=headers,
            json={
                "sku": "BOX-001",
                "name": "Shipping Box",
                "category_id": child_id,
                "unit": "piece",
                "sale_price": "12500.00",
                "purchase_cost": "8000.00",
            },
        )
        assert created.status_code == 201, created.text
        product_id = created.json()["data"]["id"]
        history = client.get(f"/api/v1/products/{product_id}/price-history")
        assert history.status_code == 200
        assert history.json()["meta"]["total_items"] == 2
        assert {item["change_type"] for item in history.json()["data"]} == {"sale", "purchase"}
        changed = client.patch(
            f"/api/v1/products/{product_id}", headers=headers, json={"purchase_cost": "8250.50"}
        )
        assert changed.status_code == 200, changed.text
        assert changed.json()["data"]["purchase_cost"] == "8250.50"
        history = client.get(f"/api/v1/products/{product_id}/price-history?change_type=purchase")
        assert history.json()["meta"]["total_items"] == 2
        assert history.json()["data"][0]["old_price"] == "8000.00"

        variant = client.post(
            f"/api/v1/products/{product_id}/variants",
            headers=headers,
            json={"sku": "BOX-001-RED", "attributes": {"color": "red"}},
        )
        assert variant.status_code == 201, variant.text
        duplicate_cross_table = client.post(
            "/api/v1/products",
            headers=headers,
            json={"sku": "BOX-001-RED", "name": "Duplicate SKU", "unit": "piece"},
        )
        assert duplicate_cross_table.status_code == 409
        duplicate_product = client.post(
            "/api/v1/products",
            headers=headers,
            json={"sku": "BOX-001", "name": "Duplicate SKU", "unit": "piece"},
        )
        assert duplicate_product.status_code == 409

        listing = client.get("/api/v1/products?query=Shipping&page=1&page_size=10")
        assert listing.status_code == 200
        assert listing.json()["meta"]["total_items"] == 1
        in_use = client.delete(f"/api/v1/categories/{child_id}", headers=headers)
        assert in_use.status_code == 409
        deleted = client.delete(f"/api/v1/products/{product_id}", headers=headers)
        assert deleted.status_code == 204
        hidden = client.get(f"/api/v1/products/{product_id}")
        assert hidden.status_code == 404
        with OrmSession(get_engine()) as db:
            history_rows = db.scalars(
                select(ProductPriceHistory).where(
                    ProductPriceHistory.tenant_id == tenant_id,
                    ProductPriceHistory.product_id == product_id,
                )
            ).all()
            assert len(history_rows) == 3
            events = db.scalars(
                select(AuditLog).where(
                    AuditLog.tenant_id == tenant_id,
                    AuditLog.entity_type.in_(["category", "product", "product_variant"]),
                )
            ).all()
            assert len(events) >= 5
    finally:
        client.close()


def test_supplier_price_list_finalization_history_and_lowest_price() -> None:
    user, tenant_id = _seed_user()
    client, headers = _client_for(user, tenant_id)
    try:
        product = client.post(
            "/api/v1/products",
            headers=headers,
            json={"sku": "TAPE-1", "name": "Packing Tape", "unit": "piece"},
        )
        assert product.status_code == 201, product.text
        product_id = product.json()["data"]["id"]
        supplier_a = client.post(
            "/api/v1/suppliers",
            headers=headers,
            json={"name": "Supplier A", "phone": "09120000000"},
        )
        supplier_b = client.post("/api/v1/suppliers", headers=headers, json={"name": "Supplier B"})
        assert supplier_a.status_code == supplier_b.status_code == 201
        invalid_email = client.post(
            "/api/v1/suppliers",
            headers=headers,
            json={"name": "Invalid Email", "email": "not-an-email"},
        )
        assert invalid_email.status_code == 422
        supplier_a_id = supplier_a.json()["data"]["id"]
        supplier_b_id = supplier_b.json()["data"]["id"]

        mismatch = client.post(
            f"/api/v1/suppliers/{supplier_a_id}/price-lists",
            headers=headers,
            json={
                "title": "Wrong currency",
                "received_at": str(date.today()),
                "items": [
                    {
                        "raw_name": "Tape",
                        "product_id": product_id,
                        "unit_price": "100",
                        "currency": "IRR",
                        "unit": "piece",
                    }
                ],
            },
        )
        assert mismatch.status_code == 422
        unit_mismatch = client.post(
            f"/api/v1/suppliers/{supplier_a_id}/price-lists",
            headers=headers,
            json={
                "title": "Wrong unit",
                "received_at": str(date.today()),
                "items": [
                    {
                        "raw_name": "Tape",
                        "product_id": product_id,
                        "unit_price": "100",
                        "currency": "IRT",
                        "unit": "box",
                    }
                ],
            },
        )
        assert unit_mismatch.status_code == 201, unit_mismatch.text
        wrong_unit_list_id = unit_mismatch.json()["data"]["id"]
        wrong_unit_final = client.post(
            f"/api/v1/price-lists/{wrong_unit_list_id}/finalize",
            headers=headers,
            json={"confirm": True},
        )
        assert wrong_unit_final.status_code == 200
        duplicate = client.post(
            f"/api/v1/suppliers/{supplier_a_id}/price-lists",
            headers=headers,
            json={
                "title": "Duplicate items",
                "received_at": str(date.today()),
                "items": [
                    {
                        "raw_name": "Tape one",
                        "sku": "TAPE-X",
                        "product_id": product_id,
                        "unit_price": "100",
                        "currency": "IRT",
                        "unit": "piece",
                    },
                    {
                        "raw_name": "Tape two",
                        "sku": "TAPE-X",
                        "product_id": product_id,
                        "unit_price": "110",
                        "currency": "IRT",
                        "unit": "piece",
                    },
                ],
            },
        )
        assert duplicate.status_code == 409

        def add_list(supplier_id: int, title: str, price: str) -> int:
            response = client.post(
                f"/api/v1/suppliers/{supplier_id}/price-lists",
                headers=headers,
                json={
                    "title": title,
                    "received_at": str(date.today()),
                    "items": [
                        {
                            "raw_name": "Packing Tape",
                            "sku": f"{title}-SKU",
                            "product_id": product_id,
                            "unit_price": price,
                            "currency": "IRT",
                            "unit": "piece",
                        }
                    ],
                },
            )
            assert response.status_code == 201, response.text
            return response.json()["data"]["id"]

        list_a = add_list(supplier_a_id, "A list", "145.25")
        list_b = add_list(supplier_b_id, "B list", "139.50")
        draft_id = add_list(supplier_a_id, "A draft", "151.00")
        draft_deleted = client.delete(f"/api/v1/price-lists/{draft_id}", headers=headers)
        assert draft_deleted.status_code == 204
        before = client.get("/api/v1/suppliers/lowest-price", params={"product_id": product_id})
        assert before.status_code == 200
        assert before.json()["data"]["lowest_price"] is None
        assert before.json()["data"]["excluded_units"] == ["box"]
        finalized_a = client.post(
            f"/api/v1/price-lists/{list_a}/finalize", headers=headers, json={"confirm": True}
        )
        finalized_b = client.post(
            f"/api/v1/price-lists/{list_b}/finalize", headers=headers, json={"confirm": True}
        )
        assert finalized_a.status_code == finalized_b.status_code == 200
        again = client.post(
            f"/api/v1/price-lists/{list_a}/finalize", headers=headers, json={"confirm": True}
        )
        assert again.status_code == 409

        detail = client.get(f"/api/v1/price-lists/{list_b}")
        assert detail.status_code == 200
        assert detail.json()["data"]["items"][0]["unit_price"] == "139.50"
        supplier_price_id = detail.json()["data"]["items"][0]["id"]
        wrong_unit_detail = client.get(f"/api/v1/price-lists/{wrong_unit_list_id}")
        wrong_unit_price_id = wrong_unit_detail.json()["data"]["items"][0]["id"]
        rejected_cost = client.post(
            f"/api/v1/products/{product_id}/purchase-cost-from-supplier-price",
            headers=headers,
            json={"supplier_price_id": wrong_unit_price_id},
        )
        assert rejected_cost.status_code == 404
        applied = client.post(
            f"/api/v1/products/{product_id}/purchase-cost-from-supplier-price",
            headers=headers,
            json={"supplier_price_id": supplier_price_id},
        )
        assert applied.status_code == 200, applied.text
        assert applied.json()["data"]["purchase_cost"] == "139.50"
        product_detail = client.get(f"/api/v1/products/{product_id}")
        assert product_detail.json()["data"]["purchase_cost"] == "139.50"
        purchase_history = client.get(
            f"/api/v1/products/{product_id}/price-history?change_type=purchase"
        )
        assert purchase_history.json()["data"][0]["source"] == "supplier_price"
        assert purchase_history.json()["data"][0]["supplier_price_id"] == supplier_price_id
        immutable = client.delete(f"/api/v1/price-lists/{list_b}", headers=headers)
        assert immutable.status_code == 409
        history = client.get(
            f"/api/v1/suppliers/{supplier_a_id}/price-history", params={"product_id": product_id}
        )
        assert history.status_code == 200
        assert len(history.json()["data"]) == 2
        lowest = client.get("/api/v1/suppliers/lowest-price", params={"product_id": product_id})
        assert lowest.status_code == 200
        assert lowest.json()["data"]["lowest_price"]["supplier_id"] == supplier_b_id
        assert lowest.json()["data"]["lowest_price"]["unit_price"] == "139.50"
        assert lowest.json()["data"]["unit"] == "piece"
        assert lowest.json()["data"]["excluded_units"] == ["box"]
        inactive = client.patch(
            f"/api/v1/suppliers/{supplier_b_id}", headers=headers, json={"is_active": False}
        )
        assert inactive.status_code == 200
        rejected_list = client.post(
            f"/api/v1/suppliers/{supplier_b_id}/price-lists",
            headers=headers,
            json={
                "title": "Inactive",
                "received_at": str(date.today()),
                "items": [
                    {
                        "raw_name": "Tape",
                        "product_id": product_id,
                        "unit_price": "130",
                        "currency": "IRT",
                        "unit": "piece",
                    }
                ],
            },
        )
        assert rejected_list.status_code == 409
        lists = client.get(f"/api/v1/suppliers/{supplier_a_id}/price-lists")
        assert lists.status_code == 200
        assert lists.json()["meta"]["total_items"] == 2
        with OrmSession(get_engine()) as db:
            row = db.get(SupplierPriceList, list_a)
            assert row is not None and row.status == "final"
    finally:
        client.close()


def test_catalog_and_supplier_routes_enforce_tenant_scope_and_permissions() -> None:
    owner, owner_tenant = _seed_user()
    outsider, outsider_tenant = _seed_user()
    client, headers = _client_for(owner, owner_tenant)
    try:
        foreign_product = client.get(f"/api/v1/products/{outsider_tenant}")
        assert foreign_product.status_code == 404
        denied = client.post(
            "/api/v1/products",
            headers=headers,
            json={"sku": "SAFE", "name": "Safe", "unit": "piece"},
        )
        assert denied.status_code == 201
        product_id = denied.json()["data"]["id"]
        outsider_client, _ = _client_for(outsider, outsider_tenant)
        try:
            cross_tenant = outsider_client.get(f"/api/v1/products/{product_id}")
            assert cross_tenant.status_code == 404
        finally:
            outsider_client.close()
    finally:
        client.close()

    viewer, viewer_tenant = _seed_user("viewer")
    viewer_client, viewer_headers = _client_for(viewer, viewer_tenant)
    try:
        allowed = viewer_client.get("/api/v1/products")
        assert allowed.status_code == 200
        denied_write = viewer_client.post(
            "/api/v1/products",
            headers=viewer_headers,
            json={"sku": "NO-WRITE", "name": "Forbidden", "unit": "piece"},
        )
        assert denied_write.status_code == 403
        denied_supplier = viewer_client.post(
            "/api/v1/suppliers", headers=viewer_headers, json={"name": "Forbidden supplier"}
        )
        assert denied_supplier.status_code == 403
    finally:
        viewer_client.close()
