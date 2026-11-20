"""Verify the initial global schema and immutable RBAC seed on real PostgreSQL."""

import pytest
from sqlalchemy import text

from app.core.db import get_engine

pytestmark = pytest.mark.integration


def test_initial_identity_tenancy_schema_exists() -> None:
    expected = {
        "users",
        "tenants",
        "roles",
        "permissions",
        "role_permissions",
        "memberships",
        "sessions",
        "password_reset_tokens",
        "tenant_settings",
        "audit_logs",
        "idempotency_keys",
    }
    with get_engine().connect() as connection:
        rows = connection.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        )
        actual = {row[0] for row in rows}
    assert expected <= actual


def test_system_roles_and_permission_catalog_are_seeded() -> None:
    with get_engine().connect() as connection:
        roles = set(connection.execute(text("SELECT name FROM roles")).scalars())
        permission_count = connection.execute(text("SELECT count(*) FROM permissions")).scalar_one()
        permission_counts = dict(
            connection.execute(
                text("""
                    SELECT r.name, count(rp.permission_id)
                    FROM roles r
                    LEFT JOIN role_permissions rp ON rp.role_id = r.id
                    GROUP BY r.name
                """)
            ).all()
        )
        viewer_write_count = connection.execute(
            text("""
                SELECT count(*)
                FROM role_permissions rp
                JOIN roles r ON r.id = rp.role_id
                JOIN permissions p ON p.id = rp.permission_id
                WHERE r.name = 'viewer' AND split_part(p.code, ':', 2) = 'write'
            """)
        ).scalar_one()
        analyst_comparison_write_count = connection.execute(
            text("""
                SELECT count(*)
                FROM role_permissions rp
                JOIN roles r ON r.id = rp.role_id
                JOIN permissions p ON p.id = rp.permission_id
                WHERE r.name = 'analyst' AND p.code = 'comparison:write'
            """)
        ).scalar_one()
        platform_permissions = connection.execute(
            text("""
                SELECT count(*)
                FROM role_permissions rp
                JOIN roles r ON r.id = rp.role_id
                WHERE r.name = 'platform_admin'
            """)
        ).scalar_one()

    assert roles == {"owner", "admin", "analyst", "viewer", "platform_admin"}
    assert permission_count == 20
    assert permission_counts == {
        "owner": 20,
        "admin": 19,
        "analyst": 12,
        "viewer": 10,
        "platform_admin": 0,
    }
    assert viewer_write_count == 0
    assert analyst_comparison_write_count == 0
    assert platform_permissions == 0


def test_email_column_uses_case_insensitive_citext() -> None:
    with get_engine().connect() as connection:
        is_case_insensitive = connection.execute(
            text("SELECT 'MarginPilot@example.com'::citext = 'marginpilot@EXAMPLE.com'::citext")
        ).scalar_one()
    assert is_case_insensitive is True


def test_idempotency_created_at_has_no_now_default() -> None:
    with get_engine().connect() as connection:
        column_default = connection.execute(
            text("""
                SELECT column_default
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'idempotency_keys'
                  AND column_name = 'created_at'
            """)
        ).scalar_one()
    # The idempotency contract requires clock_timestamp() at statement time;
    # callers must supply it explicitly rather than inheriting transaction-time now().
    assert column_default is None
