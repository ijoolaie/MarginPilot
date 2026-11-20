from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.core.models import Base
from app.modules.audit import models as audit_models  # noqa: F401
from app.modules.catalog import models as catalog_models  # noqa: F401
from app.modules.comparison import models as comparison_models  # noqa: F401
from app.modules.expenses import models as expense_models  # noqa: F401
from app.modules.identity import models as identity_models  # noqa: F401
from app.modules.imports import models as import_models  # noqa: F401
from app.modules.sales import models as sales_models  # noqa: F401
from app.modules.tenancy import models as tenancy_models  # noqa: F401


def test_phase5_tables_register_and_compile_for_postgresql() -> None:
    expected = {
        "sales_orders",
        "sale_items",
        "sales_returns",
        "sales_return_items",
        "expenses",
    }
    assert expected <= Base.metadata.tables.keys()
    for name in expected:
        ddl = str(CreateTable(Base.metadata.tables[name]).compile(dialect=postgresql.dialect()))
        assert f"CREATE TABLE {name}" in ddl


def test_sales_orders_are_immutable_financial_documents() -> None:
    table = Base.metadata.tables["sales_orders"]
    assert "deleted_at" not in table.c
    assert any(
        constraint.name == "uq_sales_orders_tenant_order_number" for constraint in table.constraints
    )


def test_sale_item_variant_fk_is_product_and_tenant_scoped() -> None:
    table = Base.metadata.tables["sale_items"]
    local_fk_sets = {
        tuple(element.parent.name for element in constraint.elements)
        for constraint in table.foreign_key_constraints
    }
    assert ("tenant_id", "product_id", "variant_id") in local_fk_sets


def test_expense_scope_requires_matching_target_fields() -> None:
    table = Base.metadata.tables["expenses"]
    constraints = {constraint.name for constraint in table.constraints}
    assert any(name.endswith("allocation_scope_fields_consistent") for name in constraints)
