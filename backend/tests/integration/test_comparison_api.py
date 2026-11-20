from __future__ import annotations

import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session as OrmSession

from app.core.db import get_engine
from app.main import app
from app.modules.audit.models import AuditLog
from app.modules.catalog.models import SupplierPrice
from app.modules.comparison.models import ComparisonMatch
from app.modules.identity.models import User
from app.modules.identity.security import hash_password
from app.modules.tenancy.models import Membership, Role
from app.modules.tenancy.service import create_tenant

pytestmark = pytest.mark.integration
ORIGIN = "https://localhost:3000"
PASSWORD = "correct horse battery staple 2026"


def _seed_user(role_name: str = "owner") -> tuple[User, int]:
    with OrmSession(get_engine()) as db:
        user = User(
            email=f"comparison-{uuid.uuid4().hex}@example.test",
            password_hash=hash_password(PASSWORD),
            full_name="Comparison Test User",
            is_active=True,
        )
        db.add(user)
        db.flush()
        tenant, _ = create_tenant(db, user, "Comparison Test Workspace")
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


def _create_supplier(client: TestClient, headers: dict[str, str], name: str) -> int:
    response = client.post("/api/v1/suppliers", headers=headers, json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


def _create_final_list(
    client: TestClient,
    headers: dict[str, str],
    supplier_id: int,
    title: str,
    items: list[dict[str, object]],
) -> int:
    created = client.post(
        f"/api/v1/suppliers/{supplier_id}/price-lists",
        headers=headers,
        json={"title": title, "received_at": str(date(2026, 11, 20)), "items": items},
    )
    assert created.status_code == 201, created.text
    list_id = created.json()["data"]["id"]
    finalized = client.post(
        f"/api/v1/price-lists/{list_id}/finalize",
        headers=headers,
        json={"confirm": True},
    )
    assert finalized.status_code == 200, finalized.text
    return list_id


def test_comparison_ambiguous_match_can_be_manually_resolved_atomically() -> None:
    user, tenant_id = _seed_user()
    client, headers = _client_for(user, tenant_id)
    try:
        supplier_a = _create_supplier(client, headers, "Comparison Supplier A")
        supplier_b = _create_supplier(client, headers, "Comparison Supplier B")
        base_list_id = _create_final_list(
            client,
            headers,
            supplier_a,
            "Base list",
            [
                {
                    "raw_name": "Packing Tape",
                    "unit_price": "100",
                    "currency": "IRT",
                    "unit": "piece",
                },
                {
                    "raw_name": "Packing-Tape",
                    "unit_price": "120",
                    "currency": "IRT",
                    "unit": "piece",
                },
            ],
        )
        target_list_id = _create_final_list(
            client,
            headers,
            supplier_b,
            "Target list",
            [{"raw_name": "Packing Tape", "unit_price": "110", "currency": "IRT", "unit": "piece"}],
        )
        product = client.post(
            "/api/v1/products",
            headers=headers,
            json={"sku": "TAPE-COMP-1", "name": "Packing Tape", "unit": "piece"},
        )
        assert product.status_code == 201, product.text
        product_id = product.json()["data"]["id"]

        payload = {
            "base_list_id": base_list_id,
            "target_list_id": target_list_id,
            "match_strategy": "normalized_name",
        }
        create_headers = {**headers, "Idempotency-Key": "comparison-run-ambiguous-001"}
        created = client.post("/api/v1/comparison/runs", headers=create_headers, json=payload)
        assert created.status_code == 201, created.text
        run_id = created.json()["data"]["id"]
        assert created.json()["data"]["summary"]["uncertain"] == 3
        assert created.json()["data"]["status"] == "pending_confirmation"

        replay = client.post("/api/v1/comparison/runs", headers=create_headers, json=payload)
        assert replay.status_code == 201
        assert replay.json() == created.json()
        conflict = client.post(
            "/api/v1/comparison/runs",
            headers=create_headers,
            json={**payload, "match_strategy": "sku"},
        )
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"

        with OrmSession(get_engine()) as db:
            base_ids = db.scalars(
                select(SupplierPrice.id)
                .where(
                    SupplierPrice.tenant_id == tenant_id,
                    SupplierPrice.price_list_id == base_list_id,
                )
                .order_by(SupplierPrice.id)
            ).all()
            target_id = db.scalar(
                select(SupplierPrice.id).where(
                    SupplierPrice.tenant_id == tenant_id,
                    SupplierPrice.price_list_id == target_list_id,
                )
            )
            assert len(base_ids) == 2 and target_id is not None
            candidate = db.scalar(
                select(ComparisonMatch).where(
                    ComparisonMatch.tenant_id == tenant_id,
                    ComparisonMatch.run_id == run_id,
                    ComparisonMatch.base_price_id == base_ids[0],
                    ComparisonMatch.target_price_id.is_(None),
                )
            )
            assert candidate is not None
            candidate_id = candidate.id

        wrong_product = client.post(
            "/api/v1/products",
            headers=headers,
            json={"sku": "TAPE-COMP-WRONG", "name": "Wrong Unit Product", "unit": "kg"},
        )
        assert wrong_product.status_code == 201, wrong_product.text
        rejected_unit = client.post(
            f"/api/v1/comparison/runs/{run_id}/confirm-matches",
            headers=headers,
            json={
                "decisions": [
                    {
                        "match_id": candidate_id,
                        "decision": "confirm",
                        "product_id": wrong_product.json()["data"]["id"],
                        "peer_price_id": target_id,
                    }
                ]
            },
        )
        assert rejected_unit.status_code == 422
        assert rejected_unit.json()["error"]["code"] == "PRODUCT_UNIT_MISMATCH"
        with OrmSession(get_engine()) as db:
            assert (
                db.scalar(
                    select(func.count(ComparisonMatch.id)).where(
                        ComparisonMatch.tenant_id == tenant_id,
                        ComparisonMatch.run_id == run_id,
                    )
                )
                == 3
            )
            untouched = db.scalars(
                select(SupplierPrice).where(
                    SupplierPrice.tenant_id == tenant_id,
                    SupplierPrice.id.in_([base_ids[0], target_id]),
                )
            ).all()
            assert all(item.product_id is None for item in untouched)
        confirmed = client.post(
            f"/api/v1/comparison/runs/{run_id}/confirm-matches",
            headers=headers,
            json={
                "decisions": [
                    {
                        "match_id": candidate_id,
                        "decision": "confirm",
                        "product_id": product_id,
                        "peer_price_id": target_id,
                    }
                ]
            },
        )
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["data"]["pending"] == 1
        detail = client.get(f"/api/v1/comparison/runs/{run_id}", headers=headers)
        assert detail.status_code == 200
        assert detail.json()["data"]["summary"]["matched"] == 1
        assert detail.json()["data"]["summary"]["uncertain"] == 1
        resolved = next(
            item for item in detail.json()["data"]["matches"] if item["id"] == candidate_id
        )
        assert resolved["target_price_id"] == target_id
        assert resolved["price_delta"] == "10.00"
        assert resolved["price_delta_pct"] == "10.0000"
        assert resolved["confirmed_product_id"] == product_id
        assert detail.json()["data"]["base_list"]["title"] == "Base list"
        assert detail.json()["data"]["target_list"]["supplier"]["name"] == "Comparison Supplier B"
        assert resolved["base_price"]["unit_price"] == "100.00"
        assert resolved["target_price"]["unit_price"] == "110.00"
        assert resolved["base_price"]["unit"] == resolved["target_price"]["unit"] == "piece"

        replay_confirm = client.post(
            f"/api/v1/comparison/runs/{run_id}/confirm-matches",
            headers=headers,
            json={
                "decisions": [
                    {
                        "match_id": candidate_id,
                        "decision": "confirm",
                        "product_id": product_id,
                        "peer_price_id": target_id,
                    }
                ]
            },
        )
        assert replay_confirm.status_code == 200
        assert replay_confirm.json()["data"]["confirmed"] == 0

        remaining = next(
            item for item in detail.json()["data"]["matches"] if item["status"] == "pending"
        )
        rejected = client.post(
            f"/api/v1/comparison/runs/{run_id}/confirm-matches",
            headers=headers,
            json={"decisions": [{"match_id": remaining["id"], "decision": "reject"}]},
        )
        assert rejected.status_code == 200, rejected.text
        assert rejected.json()["data"]["status"] == "completed"
        assert rejected.json()["data"]["pending"] == 0
        final_detail = client.get(f"/api/v1/comparison/runs/{run_id}", headers=headers)
        assert final_detail.json()["data"]["summary"]["uncertain"] == 0
        assert final_detail.json()["data"]["summary"]["removed"] == 1
        with OrmSession(get_engine()) as db:
            linked = db.scalars(
                select(SupplierPrice).where(
                    SupplierPrice.tenant_id == tenant_id,
                    SupplierPrice.id.in_([base_ids[0], target_id]),
                )
            ).all()
            assert len(linked) == 2
            assert all(item.product_id == product_id for item in linked)
            events = db.scalars(
                select(AuditLog).where(
                    AuditLog.tenant_id == tenant_id,
                    AuditLog.entity_type == "comparison_run",
                )
            ).all()
            assert len(events) == 3

        other_user, other_tenant_id = _seed_user()
        other_client, other_headers = _client_for(other_user, other_tenant_id)
        try:
            hidden = other_client.get(f"/api/v1/comparison/runs/{run_id}", headers=other_headers)
            assert hidden.status_code == 404
        finally:
            other_client.close()
    finally:
        client.close()


def test_comparison_read_permission_does_not_grant_write() -> None:
    user, tenant_id = _seed_user("analyst")
    client, headers = _client_for(user, tenant_id)
    try:
        listing = client.get("/api/v1/comparison/runs", headers=headers)
        assert listing.status_code == 200
        denied = client.post(
            "/api/v1/comparison/runs",
            headers={**headers, "Idempotency-Key": "analyst-comparison-write-001"},
            json={"base_list_id": 1, "target_list_id": 2, "match_strategy": "sku"},
        )
        assert denied.status_code == 403
    finally:
        client.close()


def test_comparison_rejects_draft_lists_and_same_list() -> None:
    user, tenant_id = _seed_user()
    client, headers = _client_for(user, tenant_id)
    try:
        supplier = _create_supplier(client, headers, "Draft Comparison Supplier")
        draft = client.post(
            f"/api/v1/suppliers/{supplier}/price-lists",
            headers=headers,
            json={
                "title": "Draft list",
                "received_at": str(date(2026, 11, 20)),
                "items": [
                    {
                        "raw_name": "Draft item",
                        "unit_price": "10",
                        "currency": "IRT",
                        "unit": "piece",
                    }
                ],
            },
        )
        assert draft.status_code == 201, draft.text
        list_id = draft.json()["data"]["id"]
        final_supplier = _create_supplier(client, headers, "Final Comparison Supplier")
        final_list_id = _create_final_list(
            client,
            headers,
            final_supplier,
            "Final list",
            [{"raw_name": "Final item", "unit_price": "15", "currency": "IRT", "unit": "piece"}],
        )
        same = client.post(
            "/api/v1/comparison/runs",
            headers={**headers, "Idempotency-Key": "comparison-same-list-001"},
            json={"base_list_id": list_id, "target_list_id": list_id, "match_strategy": "sku"},
        )
        assert same.status_code == 422
        draft_pair = client.post(
            "/api/v1/comparison/runs",
            headers={**headers, "Idempotency-Key": "comparison-draft-pair-001"},
            json={
                "base_list_id": list_id,
                "target_list_id": final_list_id,
                "match_strategy": "sku",
            },
        )
        assert draft_pair.status_code == 409
        assert draft_pair.json()["error"]["code"] == "PRICE_LIST_NOT_FINAL"
    finally:
        client.close()


def test_comparison_schema_has_nullable_sides_and_tenant_aware_foreign_keys() -> None:
    inspector = inspect(get_engine())
    columns = {item["name"]: item for item in inspector.get_columns("comparison_matches")}
    assert columns["base_price_id"]["nullable"] is True
    assert columns["target_price_id"]["nullable"] is True
    foreign_keys = inspector.get_foreign_keys("comparison_matches")
    assert any(
        item["constrained_columns"] == ["tenant_id", "base_price_id"]
        and item["referred_columns"] == ["tenant_id", "id"]
        for item in foreign_keys
    )
    assert any(
        item["constrained_columns"] == ["tenant_id", "target_price_id"]
        and item["referred_columns"] == ["tenant_id", "id"]
        for item in foreign_keys
    )
    indexes = {item["name"]: item for item in inspector.get_indexes("comparison_matches")}
    assert indexes["uq_comparison_matches_run_base_price"]["unique"] is True
    assert indexes["uq_comparison_matches_run_target_price"]["unique"] is True
    assert {
        "ix_comparison_matches_tenant_base_price",
        "ix_comparison_matches_tenant_target_price",
        "ix_comparison_matches_tenant_suggested_product",
        "ix_comparison_matches_tenant_confirmed_product",
    } <= indexes.keys()
    run_indexes = {item["name"] for item in inspector.get_indexes("comparison_runs")}
    assert {
        "ix_comparison_runs_created_by",
        "ix_comparison_runs_tenant_base_list",
        "ix_comparison_runs_tenant_target_list",
    } <= run_indexes
    checks = {
        item["name"]: item["sqltext"]
        for item in inspector.get_check_constraints("comparison_matches")
    }
    assert any(
        "base_price_id IS NOT NULL OR target_price_id IS NOT NULL" in sql for sql in checks.values()
    )


def test_rejecting_unit_mismatch_splits_new_and_removed() -> None:
    user, tenant_id = _seed_user()
    client, headers = _client_for(user, tenant_id)
    try:
        supplier_a = _create_supplier(client, headers, "Unit Supplier A")
        supplier_b = _create_supplier(client, headers, "Unit Supplier B")
        base_id = _create_final_list(
            client,
            headers,
            supplier_a,
            "kg list",
            [
                {
                    "raw_name": "Rice",
                    "sku": "RICE-UNIT-1",
                    "unit_price": "100",
                    "currency": "IRT",
                    "unit": "kg",
                },
            ],
        )
        target_id = _create_final_list(
            client,
            headers,
            supplier_b,
            "box list",
            [
                {
                    "raw_name": "Rice",
                    "sku": "RICE-UNIT-1",
                    "unit_price": "200",
                    "currency": "IRT",
                    "unit": "box",
                },
            ],
        )
        created = client.post(
            "/api/v1/comparison/runs",
            headers={**headers, "Idempotency-Key": "comparison-unit-mismatch-001"},
            json={"base_list_id": base_id, "target_list_id": target_id, "match_strategy": "sku"},
        )
        assert created.status_code == 201, created.text
        run_id = created.json()["data"]["id"]
        with OrmSession(get_engine()) as db:
            match = db.scalar(
                select(ComparisonMatch).where(
                    ComparisonMatch.tenant_id == tenant_id, ComparisonMatch.run_id == run_id
                )
            )
            assert match is not None and match.price_delta is None
            match_id = match.id
        response = client.post(
            f"/api/v1/comparison/runs/{run_id}/confirm-matches",
            headers=headers,
            json={"decisions": [{"match_id": match_id, "decision": "reject"}]},
        )
        assert response.status_code == 200, response.text
        detail = client.get(f"/api/v1/comparison/runs/{run_id}", headers=headers).json()["data"]
        assert detail["summary"]["matched"] == 0
        assert detail["summary"]["new"] == 1
        assert detail["summary"]["removed"] == 1
        assert detail["summary"]["uncertain"] == 0
        assert len(detail["matches"]) == 2
    finally:
        client.close()


def test_extreme_price_delta_percentage_fits_supported_price_range() -> None:
    user, tenant_id = _seed_user()
    client, headers = _client_for(user, tenant_id)
    try:
        supplier_a = _create_supplier(client, headers, "Minimum Price Supplier")
        supplier_b = _create_supplier(client, headers, "Maximum Price Supplier")
        base_list_id = _create_final_list(
            client,
            headers,
            supplier_a,
            "Minimum price list",
            [
                {
                    "raw_name": "Boundary item",
                    "sku": "BOUNDARY-1",
                    "unit_price": "0.01",
                    "currency": "IRT",
                    "unit": "piece",
                }
            ],
        )
        target_list_id = _create_final_list(
            client,
            headers,
            supplier_b,
            "Maximum price list",
            [
                {
                    "raw_name": "Boundary item",
                    "sku": "BOUNDARY-1",
                    "unit_price": "999999999999999999.99",
                    "currency": "IRT",
                    "unit": "piece",
                }
            ],
        )
        created = client.post(
            "/api/v1/comparison/runs",
            headers={**headers, "Idempotency-Key": "test"},
            json={
                "base_list_id": base_list_id,
                "target_list_id": target_list_id,
                "match_strategy": "sku",
            },
        )
        assert created.status_code == 201, created.text
        run_id = created.json()["data"]["id"]
        detail = client.get(f"/api/v1/comparison/runs/{run_id}", headers=headers)
        assert detail.status_code == 200, detail.text
        match = detail.json()["data"]["matches"][0]
        assert match["price_delta"] == "999999999999999999.98"
        assert match["price_delta_pct"] == "9999999999999999999800.0000"
    finally:
        client.close()
