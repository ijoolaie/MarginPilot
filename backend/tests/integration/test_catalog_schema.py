"""Catalog and supplier schema invariants on real PostgreSQL."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession

from app.core.db import get_engine
from app.modules.catalog.models import (
    Category,
    Product,
    ProductPriceHistory,
    ProductVariant,
    Supplier,
    SupplierPrice,
    SupplierPriceList,
)
from app.modules.identity.models import User
from app.modules.tenancy.models import Tenant

pytestmark = pytest.mark.integration


def _scope(db: OrmSession) -> tuple[User, Tenant, Tenant]:
    suffix = uuid.uuid4().hex
    user = User(
        email=f"catalog-{suffix}@example.test",
        password_hash="integration-test-placeholder-not-a-real-password-hash",
        full_name="Catalog Integration Test",
    )
    tenant_a = Tenant(
        name="Catalog Tenant A", slug=f"catalog-a-{suffix}", currency_code="IRT", status="active"
    )
    tenant_b = Tenant(
        name="Catalog Tenant B", slug=f"catalog-b-{suffix}", currency_code="IRT", status="active"
    )
    db.add_all([user, tenant_a, tenant_b])
    db.flush()
    return user, tenant_a, tenant_b


def _product(db: OrmSession, tenant_id: int, sku: str = "SKU-1") -> Product:
    product = Product(tenant_id=tenant_id, sku=sku, name=f"Product {sku}", unit="piece")
    db.add(product)
    db.flush()
    return product


def _supplier(db: OrmSession, tenant_id: int, name: str = "Supplier") -> Supplier:
    supplier = Supplier(tenant_id=tenant_id, name=name)
    db.add(supplier)
    db.flush()
    return supplier


def _price_list(
    db: OrmSession, user_id: int, tenant_id: int, supplier_id: int
) -> SupplierPriceList:
    price_list = SupplierPriceList(
        tenant_id=tenant_id,
        supplier_id=supplier_id,
        title="November price list",
        received_at=date(2026, 11, 19),
        source="manual",
        created_by=user_id,
    )
    db.add(price_list)
    db.flush()
    return price_list


def _expect_integrity_error(db: OrmSession, record: object) -> None:
    with pytest.raises(IntegrityError), db.begin_nested():
        db.add(record)
        db.flush()


def test_catalog_and_supplier_tables_are_created() -> None:
    from sqlalchemy import text

    expected = {
        "categories",
        "products",
        "product_variants",
        "product_price_history",
        "suppliers",
        "supplier_price_lists",
        "supplier_prices",
    }
    with get_engine().connect() as connection:
        actual = set(
            connection.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            ).scalars()
        )
    assert expected <= actual


def test_composite_foreign_keys_reject_cross_tenant_relationships() -> None:
    with OrmSession(get_engine()) as db:
        user, tenant_a, tenant_b = _scope(db)
        category_b = Category(tenant_id=tenant_b.id, name="Tenant B category")
        product_a = _product(db, tenant_a.id)
        product_b = _product(db, tenant_b.id)
        supplier_b = _supplier(db, tenant_b.id)
        supplier_a = _supplier(db, tenant_a.id)
        db.add(category_b)
        db.flush()
        list_b = _price_list(db, user.id, tenant_b.id, supplier_b.id)
        list_a = _price_list(db, user.id, tenant_a.id, supplier_a.id)
        price_b = SupplierPrice(
            tenant_id=tenant_b.id,
            price_list_id=list_b.id,
            raw_name="B item",
            unit_price=Decimal("10.00"),
            currency="IRT",
        )
        db.add(price_b)
        db.flush()

        _expect_integrity_error(
            db, Category(tenant_id=tenant_a.id, parent_id=category_b.id, name="Cross parent")
        )
        _expect_integrity_error(
            db,
            Product(
                tenant_id=tenant_a.id,
                category_id=category_b.id,
                sku="CROSS-CATEGORY",
                name="Cross category",
                unit="piece",
            ),
        )
        _expect_integrity_error(
            db,
            ProductVariant(
                tenant_id=tenant_a.id,
                product_id=product_b.id,
                sku="CROSS-PRODUCT",
            ),
        )
        _expect_integrity_error(
            db,
            SupplierPriceList(
                tenant_id=tenant_a.id,
                supplier_id=supplier_b.id,
                title="Cross supplier",
                received_at=date(2026, 11, 19),
                source="manual",
                created_by=user.id,
            ),
        )
        _expect_integrity_error(
            db,
            SupplierPrice(
                tenant_id=tenant_a.id,
                price_list_id=list_b.id,
                raw_name="Cross list",
                unit_price=Decimal("1.00"),
                currency="IRT",
            ),
        )
        _expect_integrity_error(
            db,
            SupplierPrice(
                tenant_id=tenant_a.id,
                price_list_id=list_a.id,
                product_id=product_b.id,
                raw_name="Cross product link",
                unit_price=Decimal("1.00"),
                currency="IRT",
            ),
        )
        _expect_integrity_error(
            db,
            ProductPriceHistory(
                tenant_id=tenant_a.id,
                product_id=product_b.id,
                change_type="purchase",
                new_price=Decimal("9.00"),
                source="manual",
            ),
        )
        _expect_integrity_error(
            db,
            ProductPriceHistory(
                tenant_id=tenant_a.id,
                product_id=product_a.id,
                change_type="purchase",
                new_price=Decimal("9.00"),
                source="supplier_price",
                supplier_price_id=price_b.id,
            ),
        )


def test_category_partial_unique_indexes_allow_reuse_after_soft_delete() -> None:
    with OrmSession(get_engine()) as db:
        _, tenant_a, _ = _scope(db)
        root = Category(tenant_id=tenant_a.id, name="Accessories")
        other_root = Category(tenant_id=tenant_a.id, name="Clothing")
        db.add_all([root, other_root])
        db.flush()
        _expect_integrity_error(db, Category(tenant_id=tenant_a.id, name="Accessories"))

        with pytest.raises(IntegrityError), db.begin_nested():
            db.execute(
                text("UPDATE categories SET parent_id = id WHERE id = :category_id"),
                {"category_id": root.id},
            )

        root.deleted_at = datetime.now(UTC)
        db.flush()
        replacement = Category(tenant_id=tenant_a.id, name="Accessories")
        db.add(replacement)
        db.flush()

        child = Category(tenant_id=tenant_a.id, parent_id=other_root.id, name="Sale")
        db.add(child)
        db.flush()
        _expect_integrity_error(
            db, Category(tenant_id=tenant_a.id, parent_id=other_root.id, name="Sale")
        )
        db.add(Category(tenant_id=tenant_a.id, parent_id=replacement.id, name="Sale"))
        db.flush()


def test_product_and_variant_sku_partial_uniqueness_and_soft_delete() -> None:
    with OrmSession(get_engine()) as db:
        _, tenant_a, _ = _scope(db)
        product = _product(db, tenant_a.id, "SHARED-SKU")
        _expect_integrity_error(
            db, Product(tenant_id=tenant_a.id, sku="SHARED-SKU", name="Duplicate", unit="piece")
        )

        product.deleted_at = datetime.now(UTC)
        db.flush()
        replacement = _product(db, tenant_a.id, "SHARED-SKU")

        # Cross-table product/variant SKU uniqueness is intentionally a service invariant in v1.
        db.add(ProductVariant(tenant_id=tenant_a.id, product_id=replacement.id, sku="SHARED-SKU"))
        db.flush()
        _expect_integrity_error(
            db,
            ProductVariant(tenant_id=tenant_a.id, product_id=replacement.id, sku="SHARED-SKU"),
        )


def test_supplier_price_list_item_partial_unique_indexes() -> None:
    with OrmSession(get_engine()) as db:
        user, tenant_a, _ = _scope(db)
        supplier = _supplier(db, tenant_a.id)
        price_list = _price_list(db, user.id, tenant_a.id, supplier.id)
        db.add_all(
            [
                SupplierPrice(
                    tenant_id=tenant_a.id,
                    price_list_id=price_list.id,
                    raw_name="same display name",
                    sku="SKU-1",
                    unit_price=Decimal("10.25"),
                    currency="IRT",
                ),
                SupplierPrice(
                    tenant_id=tenant_a.id,
                    price_list_id=price_list.id,
                    raw_name="same display name",
                    sku="SKU-2",
                    unit_price=Decimal("11.75"),
                    currency="IRT",
                ),
            ]
        )
        db.flush()
        _expect_integrity_error(
            db,
            SupplierPrice(
                tenant_id=tenant_a.id,
                price_list_id=price_list.id,
                raw_name="another name",
                sku="SKU-1",
                unit_price=Decimal("12.00"),
                currency="IRT",
            ),
        )
        db.add(
            SupplierPrice(
                tenant_id=tenant_a.id,
                price_list_id=price_list.id,
                raw_name="unmatched item",
                sku=None,
                unit_price=Decimal("0.00"),
                currency="IRT",
            )
        )
        db.flush()
        _expect_integrity_error(
            db,
            SupplierPrice(
                tenant_id=tenant_a.id,
                price_list_id=price_list.id,
                raw_name="unmatched item",
                sku=None,
                unit_price=Decimal("1.00"),
                currency="IRT",
            ),
        )


def test_price_history_requires_supplier_provenance_pair_and_preserves_decimal() -> None:
    with OrmSession(get_engine()) as db:
        user, tenant_a, _ = _scope(db)
        product = _product(db, tenant_a.id)
        supplier = _supplier(db, tenant_a.id)
        price_list = _price_list(db, user.id, tenant_a.id, supplier.id)
        supplier_price = SupplierPrice(
            tenant_id=tenant_a.id,
            price_list_id=price_list.id,
            product_id=product.id,
            raw_name=product.name,
            sku=product.sku,
            unit_price=Decimal("1234.56"),
            currency="IRT",
        )
        db.add(supplier_price)
        db.flush()

        _expect_integrity_error(
            db,
            ProductPriceHistory(
                tenant_id=tenant_a.id,
                product_id=product.id,
                change_type="purchase",
                new_price=Decimal("1234.56"),
                source="supplier_price",
            ),
        )
        _expect_integrity_error(
            db,
            ProductPriceHistory(
                tenant_id=tenant_a.id,
                product_id=product.id,
                change_type="purchase",
                new_price=Decimal("1234.56"),
                source="manual",
                supplier_price_id=supplier_price.id,
            ),
        )
        history = ProductPriceHistory(
            tenant_id=tenant_a.id,
            product_id=product.id,
            change_type="purchase",
            old_price=Decimal("1200.00"),
            new_price=Decimal("1234.56"),
            changed_by=user.id,
            source="supplier_price",
            supplier_price_id=supplier_price.id,
        )
        db.add(history)
        db.flush()
        db.refresh(supplier_price)
        assert supplier_price.unit_price == Decimal("1234.56")
        assert history.new_price == Decimal("1234.56")


def test_database_rejects_invalid_catalog_and_price_values() -> None:
    with OrmSession(get_engine()) as db:
        user, tenant_a, _ = _scope(db)
        supplier = _supplier(db, tenant_a.id)
        price_list = _price_list(db, user.id, tenant_a.id, supplier.id)
        _expect_integrity_error(
            db,
            Product(tenant_id=tenant_a.id, sku="BAD-UNIT", name="Bad unit", unit="gram"),
        )
        json_product = _product(db, tenant_a.id, "JSON-TEST")
        _expect_integrity_error(
            db,
            ProductVariant(
                tenant_id=tenant_a.id,
                product_id=json_product.id,
                sku="BAD-ATTRIBUTES",
                attributes=["not", "an", "object"],
            ),
        )
        _expect_integrity_error(
            db,
            Product(
                tenant_id=tenant_a.id,
                sku="NEGATIVE",
                name="Negative",
                unit="piece",
                sale_price=Decimal("-1.00"),
            ),
        )
        _expect_integrity_error(
            db,
            SupplierPrice(
                tenant_id=tenant_a.id,
                price_list_id=price_list.id,
                raw_name="Negative price",
                unit_price=Decimal("-0.01"),
                currency="IRT",
            ),
        )
        _expect_integrity_error(
            db,
            SupplierPrice(
                tenant_id=tenant_a.id,
                price_list_id=price_list.id,
                raw_name="Blank SKU",
                sku="   ",
                unit_price=Decimal("1.00"),
                currency="IRT",
            ),
        )
        _expect_integrity_error(
            db,
            SupplierPrice(
                tenant_id=tenant_a.id,
                price_list_id=price_list.id,
                raw_name="Invalid currency",
                unit_price=Decimal("1.00"),
                currency="USD",
            ),
        )


def test_supplier_price_unit_constraint_allows_legacy_null_and_rejects_unknown() -> None:
    constraints = inspect(get_engine()).get_check_constraints("supplier_prices")
    assert any(item["name"] == "ck_supplier_prices_unit_allowed" for item in constraints)
    with OrmSession(get_engine()) as db, db.begin():
        user, tenant, _ = _scope(db)
        product = _product(db, tenant.id)
        supplier = _supplier(db, tenant.id)
        price_list = _price_list(db, user.id, tenant.id, supplier.id)
        legacy = SupplierPrice(
            tenant_id=tenant.id,
            price_list_id=price_list.id,
            product_id=product.id,
            raw_name="Legacy item",
            sku="LEGACY-UNIT",
            unit_price=Decimal("12.50"),
            currency="IRT",
            unit=None,
        )
        db.add(legacy)
        db.flush()
        assert legacy.unit is None
        valid = SupplierPrice(
            tenant_id=tenant.id,
            price_list_id=price_list.id,
            product_id=product.id,
            raw_name="Different supplier unit",
            sku="BOX-UNIT",
            unit_price=Decimal("99.00"),
            currency="IRT",
            unit="box",
        )
        db.add(valid)
        db.flush()
        _expect_integrity_error(
            db,
            SupplierPrice(
                tenant_id=tenant.id,
                price_list_id=price_list.id,
                product_id=product.id,
                raw_name="Invalid unit",
                sku="INVALID-UNIT",
                unit_price=Decimal("10.00"),
                currency="IRT",
                unit="bundle",
            ),
        )
