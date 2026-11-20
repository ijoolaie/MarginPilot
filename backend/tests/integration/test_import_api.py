from __future__ import annotations

import io
import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook  # type: ignore[import-untyped]
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession

from app.core.db import get_engine
from app.main import app
from app.modules.audit.models import AuditLog
from app.modules.catalog.models import (
    Product,
    ProductPriceHistory,
    Supplier,
    SupplierPrice,
    SupplierPriceList,
)
from app.modules.identity.models import User
from app.modules.identity.security import hash_password
from app.modules.imports.models import ImportBatch, ImportRow
from app.modules.tenancy.models import Membership, Role
from app.modules.tenancy.service import create_tenant

pytestmark = pytest.mark.integration
ORIGIN = "https://localhost:3000"
PASSWORD = "correct horse battery staple 2026"


def _seed_user(role_name: str = "owner") -> tuple[User, int]:
    with OrmSession(get_engine()) as db:
        user = User(
            email=f"imports-{uuid.uuid4().hex}@example.test",
            password_hash=hash_password(PASSWORD),
            full_name="Import Test User",
            is_active=True,
        )
        db.add(user)
        db.flush()
        tenant, _ = create_tenant(db, user, "Import Test Workspace")
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


def _upload_products(client: TestClient, headers: dict[str, str], content: bytes | None = None):
    data = content or (
        b"SKU;Name;Unit;Purchase;Sale\n"
        b"SKU-IMP-1;Packing Tape;piece;1000.00;1500.00\n"
        b"SKU-IMP-1;Duplicate Tape;piece;2000;2500\n"
        b";Missing SKU;piece;100;200\n"
    )
    return client.post(
        "/api/v1/imports",
        headers=headers,
        data={"kind": "products"},
        files={"file": ("..\\..\\products.csv", data, "text/csv")},
    )


def _product_mapping(client: TestClient, headers: dict[str, str], import_id: int):
    return client.patch(
        f"/api/v1/imports/{import_id}/mapping",
        headers=headers,
        json={
            "mapping": {
                "sku": "SKU",
                "name": "Name",
                "unit": "Unit",
                "purchase_cost": "Purchase",
                "sale_price": "Sale",
            }
        },
    )


def test_product_import_preview_commit_idempotency_and_history() -> None:
    user, tenant_id = _seed_user()
    client, headers = _client_for(user, tenant_id)
    try:
        uploaded = _upload_products(client, headers)
        assert uploaded.status_code == 201, uploaded.text
        upload_data = uploaded.json()["data"]
        import_id = upload_data["id"]
        assert upload_data["status"] == "parsed"
        assert upload_data["file_name"] == "products.csv"
        assert len(upload_data["file_hash"]) == 64

        preview = _product_mapping(client, headers, import_id)
        assert preview.status_code == 200, preview.text
        preview_data = preview.json()["data"]
        assert preview_data["status"] == "awaiting_confirmation"
        assert preview_data["stats"] == {
            "total_rows": 3,
            "valid_rows": 1,
            "error_rows": 1,
            "duplicate_rows": 1,
            "skipped_rows": 2,
            "committed_rows": 0,
        }
        errors = client.get(f"/api/v1/imports/{import_id}/rows?status=error", headers=headers)
        assert errors.status_code == 200
        assert errors.json()["meta"]["total_items"] == 1
        error_report = client.get(f"/api/v1/imports/{import_id}/error-report.xlsx", headers=headers)
        assert error_report.status_code == 200
        assert error_report.headers["content-type"].startswith(
            "application/vnd.openxmlformats-officedocument"
        )
        assert error_report.content.startswith(b"PK")

        missing_key = client.post(f"/api/v1/imports/{import_id}/confirm", headers=headers)
        assert missing_key.status_code == 422
        preflight = client.options(
            f"/api/v1/imports/{import_id}/confirm",
            headers={
                "Origin": ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "x-csrf-token,idempotency-key",
            },
        )
        assert preflight.status_code == 200
        assert "idempotency-key" in preflight.headers["access-control-allow-headers"].lower()
        confirm_headers = {**headers, "Idempotency-Key": "import-products-confirm-001"}
        confirmed = client.post(f"/api/v1/imports/{import_id}/confirm", headers=confirm_headers)
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["data"]["committed_rows"] == 1
        assert confirmed.json()["data"]["skipped_rows"] == 2
        assert confirmed.json()["data"]["status"] == "committed"

        replay = client.post(f"/api/v1/imports/{import_id}/confirm", headers=confirm_headers)
        assert replay.status_code == 200
        assert replay.json() == confirmed.json()
        different_key = client.post(
            f"/api/v1/imports/{import_id}/confirm",
            headers={**headers, "Idempotency-Key": "import-products-confirm-002"},
        )
        assert different_key.status_code == 409

        listing = client.get("/api/v1/imports?kind=products", headers=headers)
        assert listing.status_code == 200 and listing.json()["meta"]["total_items"] == 1
        deleted = client.delete(f"/api/v1/imports/{import_id}", headers=headers)
        assert deleted.status_code == 409
        with OrmSession(get_engine()) as db:
            product = db.scalar(
                select(Product).where(Product.tenant_id == tenant_id, Product.sku == "SKU-IMP-1")
            )
            assert product is not None
            assert product.purchase_cost is not None and str(product.purchase_cost) == "1000.00"
            assert product.sale_price is not None and str(product.sale_price) == "1500.00"
            history = db.scalars(
                select(ProductPriceHistory).where(
                    ProductPriceHistory.tenant_id == tenant_id,
                    ProductPriceHistory.product_id == product.id,
                )
            ).all()
            assert {
                (row.change_type, row.source, row.old_price, row.new_price) for row in history
            } == {
                ("purchase", "import", None, product.purchase_cost),
                ("sale", "import", None, product.sale_price),
            }
            batch = db.get(ImportBatch, import_id)
            assert batch is not None and batch.status == "committed"
            rows = db.scalars(select(ImportRow).where(ImportRow.import_id == import_id)).all()
            assert len(rows) == 3
            events = db.scalars(
                select(AuditLog).where(
                    AuditLog.tenant_id == tenant_id, AuditLog.entity_type == "import"
                )
            ).all()
            assert {event.action for event in events} >= {
                "import.uploaded",
                "import.validated",
                "import.committed",
            }
    finally:
        client.close()


def test_supplier_price_import_creates_draft_without_changing_product_cost() -> None:
    user, tenant_id = _seed_user()
    client, headers = _client_for(user, tenant_id)
    try:
        supplier = client.post(
            "/api/v1/suppliers", headers=headers, json={"name": "Import Supplier"}
        )
        assert supplier.status_code == 201, supplier.text
        supplier_id = supplier.json()["data"]["id"]
        missing_date = client.post(
            "/api/v1/imports",
            headers=headers,
            data={"kind": "supplier_prices", "supplier_id": str(supplier_id)},
            files={"file": ("supplier.csv", b"Name,Price,Unit\\nBox,10,piece\\n", "text/csv")},
        )
        assert missing_date.status_code == 422
        assert missing_date.json()["error"]["code"] == "RECEIVED_AT_REQUIRED"

        csv_data = (
            b"Name;SKU;Price;Unit;Currency\n"
            b"Carton Box;BOX-IMP;12000.00;piece;IRT\n"
            b"Wrong Currency;BOX-ERR;15000.00;piece;IRR\n"
        )
        uploaded = client.post(
            "/api/v1/imports",
            headers=headers,
            data={
                "kind": "supplier_prices",
                "supplier_id": str(supplier_id),
                "price_list_title": "November supplier list",
                "received_at": str(date(2026, 11, 19)),
            },
            files={"file": ("supplier.csv", csv_data, "text/csv")},
        )
        assert uploaded.status_code == 201, uploaded.text
        import_id = uploaded.json()["data"]["id"]
        mapped = client.patch(
            f"/api/v1/imports/{import_id}/mapping",
            headers=headers,
            json={
                "mapping": {
                    "raw_name": "Name",
                    "sku": "SKU",
                    "unit_price": "Price",
                    "unit": "Unit",
                    "currency": "Currency",
                }
            },
        )
        assert mapped.status_code == 200, mapped.text
        assert mapped.json()["data"]["stats"]["valid_rows"] == 1
        assert mapped.json()["data"]["stats"]["error_rows"] == 1
        confirmed = client.post(
            f"/api/v1/imports/{import_id}/confirm",
            headers={**headers, "Idempotency-Key": "import-supplier-confirm-001"},
        )
        assert confirmed.status_code == 200, confirmed.text
        price_list_id = confirmed.json()["data"]["supplier_price_list_id"]
        with OrmSession(get_engine()) as db:
            price_list = db.get(SupplierPriceList, price_list_id)
            assert price_list is not None
            assert price_list.source == "import" and price_list.status == "draft"
            prices = db.scalars(
                select(SupplierPrice).where(SupplierPrice.price_list_id == price_list_id)
            ).all()
            assert len(prices) == 1
            assert prices[0].product_id is None
            assert prices[0].currency == "IRT" and prices[0].unit == "piece"
        finalized = client.post(
            f"/api/v1/price-lists/{price_list_id}/finalize", headers=headers, json={"confirm": True}
        )
        assert finalized.status_code == 200, finalized.text
    finally:
        client.close()


def test_import_confirmation_rolls_back_and_same_idempotency_key_can_retry() -> None:
    user, tenant_id = _seed_user()
    client, headers = _client_for(user, tenant_id)
    try:
        uploaded = _upload_products(
            client, headers, b"SKU,Name,Unit\nRETRY-1,Retry Product,piece\n"
        )
        assert uploaded.status_code == 201, uploaded.text
        import_id = uploaded.json()["data"]["id"]
        mapped = client.patch(
            f"/api/v1/imports/{import_id}/mapping",
            headers=headers,
            json={"mapping": {"sku": "SKU", "name": "Name", "unit": "Unit"}},
        )
        assert mapped.status_code == 200 and mapped.json()["data"]["stats"]["valid_rows"] == 1
        conflict = client.post(
            "/api/v1/products",
            headers=headers,
            json={"sku": "RETRY-1", "name": "Racing Product", "unit": "piece"},
        )
        assert conflict.status_code == 201
        retry_headers = {**headers, "Idempotency-Key": "import-atomic-retry-001"}
        failed = client.post(f"/api/v1/imports/{import_id}/confirm", headers=retry_headers)
        assert failed.status_code == 409
        assert failed.json()["error"]["code"] == "SKU_ALREADY_EXISTS"
        with OrmSession(get_engine()) as db:
            batch = db.get(ImportBatch, import_id)
            assert batch is not None and batch.status == "awaiting_confirmation"
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(Product)
                    .where(Product.tenant_id == tenant_id, Product.sku == "RETRY-1")
                )
                == 1
            )
        client.delete(f"/api/v1/products/{conflict.json()['data']['id']}", headers=headers)
        succeeded = client.post(f"/api/v1/imports/{import_id}/confirm", headers=retry_headers)
        assert succeeded.status_code == 200, succeeded.text
        assert succeeded.json()["data"]["committed_rows"] == 1
    finally:
        client.close()


def test_import_tenant_isolation_permissions_and_unsupported_kind() -> None:
    owner, owner_tenant = _seed_user()
    other, other_tenant = _seed_user()
    viewer, viewer_tenant = _seed_user("viewer")
    owner_client, owner_headers = _client_for(owner, owner_tenant)
    other_client, other_headers = _client_for(other, other_tenant)
    viewer_client, viewer_headers = _client_for(viewer, viewer_tenant)
    try:
        uploaded = _upload_products(
            owner_client, owner_headers, b"SKU,Name,Unit\nISO-1,Isolation,piece\n"
        )
        assert uploaded.status_code == 201, uploaded.text
        import_id = uploaded.json()["data"]["id"]
        assert (
            other_client.get(f"/api/v1/imports/{import_id}", headers=other_headers).status_code
            == 404
        )
        assert (
            other_client.patch(
                f"/api/v1/imports/{import_id}/mapping",
                headers=other_headers,
                json={"mapping": {"sku": "SKU", "name": "Name", "unit": "Unit"}},
            ).status_code
            == 404
        )
        denied = _upload_products(
            viewer_client, viewer_headers, b"SKU,Name,Unit\nV-1,Viewer,piece\n"
        )
        assert denied.status_code == 403
        unsupported = owner_client.post(
            "/api/v1/imports",
            headers=owner_headers,
            data={"kind": "sales"},
            files={"file": ("sales.csv", b"a,b\n1,2\n", "text/csv")},
        )
        assert unsupported.status_code == 422
        deleted = owner_client.delete(f"/api/v1/imports/{import_id}", headers=owner_headers)
        assert deleted.status_code == 204
        with OrmSession(get_engine()) as db:
            assert db.get(ImportBatch, import_id) is None
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(ImportRow)
                    .where(ImportRow.import_id == import_id)
                )
                == 0
            )
    finally:
        owner_client.close()
        other_client.close()
        viewer_client.close()


def test_xlsx_upload_and_invalid_uploads() -> None:
    user, tenant_id = _seed_user()
    client, headers = _client_for(user, tenant_id)
    try:
        workbook = Workbook()
        sheet = workbook.active
        assert sheet is not None
        sheet.title = "Catalog"
        sheet.append(["Code", "Product", "Measure"])
        sheet.append(["XLSX-1", "XLSX Product", "piece"])
        output = io.BytesIO()
        workbook.save(output)
        payload = output.getvalue()
        uploaded = client.post(
            "/api/v1/imports",
            headers=headers,
            data={"kind": "products", "sheet_name": "Catalog"},
            files={
                "file": (
                    "catalog.xlsx",
                    payload,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
        assert uploaded.status_code == 201, uploaded.text
        import_id = uploaded.json()["data"]["id"]
        assert uploaded.json()["data"]["sheet_name"] == "Catalog"
        mapped = client.patch(
            f"/api/v1/imports/{import_id}/mapping",
            headers=headers,
            json={"mapping": {"sku": "Code", "name": "Product", "unit": "Measure"}},
        )
        assert mapped.status_code == 200 and mapped.json()["data"]["stats"]["valid_rows"] == 1
        confirmed = client.post(
            f"/api/v1/imports/{import_id}/confirm",
            headers={**headers, "Idempotency-Key": "import-xlsx-confirm-001"},
        )
        assert confirmed.status_code == 200, confirmed.text

        wrong_extension = client.post(
            "/api/v1/imports",
            headers=headers,
            data={"kind": "products"},
            files={"file": ("catalog.xlsm", payload, "application/octet-stream")},
        )
        assert wrong_extension.status_code == 422
        wrong_mime = client.post(
            "/api/v1/imports",
            headers=headers,
            data={"kind": "products"},
            files={"file": ("catalog.csv", b"a,b\\n1,2\\n", "application/pdf")},
        )
        assert wrong_mime.status_code == 422
    finally:
        client.close()


def test_import_and_import_row_composite_foreign_keys_are_tenant_scoped() -> None:
    owner, tenant_id = _seed_user()
    other, other_tenant_id = _seed_user()
    client, headers = _client_for(owner, tenant_id)
    try:
        uploaded = _upload_products(client, headers, b"SKU,Name,Unit\nFK-1,Foreign Key,piece\n")
        assert uploaded.status_code == 201, uploaded.text
        import_id = uploaded.json()["data"]["id"]
        with OrmSession(get_engine()) as db:
            db.add(
                ImportRow(
                    tenant_id=other_tenant_id, import_id=import_id, row_number=2, raw={"SKU": "x"}
                )
            )
            with pytest.raises(IntegrityError):
                db.flush()
            db.rollback()

            supplier = db.scalar(select(Supplier).where(Supplier.tenant_id == tenant_id))
            assert supplier is None
            db.add(Supplier(tenant_id=tenant_id, name="Tenant-bound supplier", is_active=True))
            db.flush()
            supplier = db.scalar(select(Supplier).where(Supplier.tenant_id == tenant_id))
            assert supplier is not None
            db.add(
                ImportBatch(
                    tenant_id=other_tenant_id,
                    created_by=other.id,
                    kind="supplier_prices",
                    status="parsed",
                    file_name="cross-tenant.csv",
                    file_hash="a" * 64,
                    file_size_bytes=10,
                    mime_type="text/csv",
                    column_headers=["Name"],
                    mapping={},
                    stats={},
                    supplier_id=supplier.id,
                    price_list_title="Invalid cross-tenant list",
                    received_at=date(2026, 11, 19),
                )
            )
            with pytest.raises(IntegrityError):
                db.flush()
            db.rollback()
    finally:
        client.close()
