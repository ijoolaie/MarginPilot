"""Initial global schema for identity, tenancy, audit and idempotency."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_identity_tenancy"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # citext provides case-insensitive email uniqueness as specified by the data model.
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")

    op.create_table(
        "tenants",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("slug", sa.String(80), nullable=False),
        sa.Column("currency_code", sa.String(3), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "currency_code IN ('IRT', 'IRR')", name="ck_tenants_currency_code_allowed"
        ),
        sa.CheckConstraint("status IN ('active', 'suspended')", name="ck_tenants_status_allowed"),
        sa.UniqueConstraint("slug", name="uq_tenants_slug"),
    )
    op.create_table(
        "roles",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("name", sa.String(40), nullable=False),
        sa.Column("description", sa.String(255)),
        sa.Column("is_system", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.CheckConstraint(
            "name IN ('owner', 'admin', 'analyst', 'viewer', 'platform_admin')",
            name="ck_roles_name_allowed",
        ),
        sa.UniqueConstraint("name", name="uq_roles_name"),
    )
    op.create_table(
        "permissions",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("description", sa.String(255), nullable=False),
        sa.UniqueConstraint("code", name="uq_permissions_code"),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(160), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("is_platform_admin", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("failed_login_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_table(
        "tenant_settings",
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "default_allocation_strategy",
            sa.String(40),
            nullable=False,
        ),
        sa.Column("currency_display", sa.String(16), nullable=False),
        sa.Column("round_display_decimals", sa.Integer(), nullable=False),
        sa.Column(
            "extra",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
            name="fk_tenant_settings_tenant_id_tenants",
        ),
        sa.PrimaryKeyConstraint("tenant_id", name="pk_tenant_settings"),
    )
    op.create_table(
        "memberships",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("role_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('active', 'invited', 'revoked')", name="ck_memberships_status_allowed"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE", name="fk_memberships_user_id_users"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
            name="fk_memberships_tenant_id_tenants",
        ),
        sa.ForeignKeyConstraint(
            ["role_id"], ["roles.id"], ondelete="RESTRICT", name="fk_memberships_role_id_roles"
        ),
        sa.UniqueConstraint("user_id", "tenant_id", name="uq_memberships_user_tenant"),
    )
    op.create_table(
        "role_permissions",
        sa.Column("role_id", sa.BigInteger(), nullable=False),
        sa.Column("permission_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["role_id"], ["roles.id"], ondelete="CASCADE", name="fk_role_permissions_role_id_roles"
        ),
        sa.ForeignKeyConstraint(
            ["permission_id"],
            ["permissions.id"],
            ondelete="CASCADE",
            name="fk_role_permissions_permission_id_permissions",
        ),
        sa.PrimaryKeyConstraint("role_id", "permission_id", name="pk_role_permissions"),
    )
    op.create_table(
        "sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("tenant_id", sa.BigInteger()),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("csrf_token_hash", sa.String(64), nullable=False),
        sa.Column("ip", sa.String(45)),
        sa.Column("user_agent", sa.String(512)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("idle_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("absolute_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_reason", sa.String(80)),
        sa.CheckConstraint(
            "idle_expires_at <= absolute_expires_at", name="ck_sessions_idle_before_absolute_expiry"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE", name="fk_sessions_user_id_users"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="SET NULL", name="fk_sessions_tenant_id_tenants"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_sessions"),
        sa.UniqueConstraint("token_hash", name="uq_sessions_token_hash"),
    )
    op.create_index("ix_sessions_idle_expires_at", "sessions", ["idle_expires_at"])
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
            name="fk_password_reset_tokens_user_id_users",
        ),
        sa.UniqueConstraint("token_hash", name="uq_password_reset_tokens_token_hash"),
    )
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger()),
        sa.Column("user_id", sa.BigInteger()),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.Text()),
        sa.Column(
            "detail",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("ip", sa.String(45)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="SET NULL",
            name="fk_audit_logs_tenant_id_tenants",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="SET NULL", name="fk_audit_logs_user_id_users"
        ),
    )
    op.create_index("ix_audit_logs_tenant_created_at", "audit_logs", ["tenant_id", "created_at"])
    op.create_table(
        "idempotency_keys",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("operation", sa.String(100), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("response_status", sa.Integer()),
        sa.Column("response_body", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(response_status IS NULL) = (response_body IS NULL)",
            name="ck_idempotency_keys_response_status_body_pair",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
            name="fk_idempotency_keys_tenant_id_tenants",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE", name="fk_idempotency_keys_user_id_users"
        ),
        sa.UniqueConstraint(
            "tenant_id", "user_id", "idempotency_key", name="uq_idempotency_scope_key"
        ),
    )
    op.create_index("ix_idempotency_keys_expires_at", "idempotency_keys", ["expires_at"])

    # Static system roles and the exact permission vocabulary from security.md.
    op.execute("""
        INSERT INTO roles (name, description, is_system) VALUES
        ('owner', 'Tenant owner', true),
        ('admin', 'Tenant administrator', true),
        ('analyst', 'Read and analyze business data', true),
        ('viewer', 'Read-only tenant access', true),
        ('platform_admin', 'Platform-level administration only', true)
        ON CONFLICT (name) DO NOTHING
    """)
    op.execute("""
        INSERT INTO permissions (code, description) VALUES
        ('product:read', 'Read products'), ('product:write', 'Manage products'),
        ('supplier:read', 'Read suppliers'), ('supplier:write', 'Manage suppliers'),
        ('sales:read', 'Read sales'), ('sales:write', 'Manage sales'),
        ('expense:read', 'Read expenses'), ('expense:write', 'Manage expenses'),
        ('import:read', 'Read imports'), ('import:execute', 'Execute imports'),
        ('pricing:read', 'Read pricing'), ('analytics:read', 'Read analytics'),
        ('report:read', 'Read reports'), ('report:generate', 'Generate reports'),
        ('comparison:read', 'Read comparisons'), ('comparison:write', 'Manage comparisons'),
        ('member:read', 'Read tenant members'), ('member:manage', 'Manage tenant members'),
        ('tenant:manage', 'Manage tenant'), ('settings:write', 'Write settings')
        ON CONFLICT (code) DO NOTHING
    """)
    op.execute("""
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id
        FROM (VALUES
            ('owner','product:read'),('owner','product:write'),('owner','supplier:read'),('owner','supplier:write'),
            ('owner','sales:read'),('owner','sales:write'),('owner','expense:read'),('owner','expense:write'),
            ('owner','import:read'),('owner','import:execute'),('owner','pricing:read'),('owner','analytics:read'),
            ('owner','report:read'),('owner','report:generate'),('owner','comparison:read'),('owner','comparison:write'),
            ('owner','member:read'),('owner','member:manage'),('owner','tenant:manage'),('owner','settings:write'),
            ('admin','product:read'),('admin','product:write'),('admin','supplier:read'),('admin','supplier:write'),
            ('admin','sales:read'),('admin','sales:write'),('admin','expense:read'),('admin','expense:write'),
            ('admin','import:read'),('admin','import:execute'),('admin','pricing:read'),('admin','analytics:read'),
            ('admin','report:read'),('admin','report:generate'),('admin','comparison:read'),('admin','comparison:write'),
            ('admin','member:read'),('admin','member:manage'),('admin','settings:write'),
            ('analyst','product:read'),('analyst','supplier:read'),('analyst','sales:read'),('analyst','expense:read'),
            ('analyst','import:read'),('analyst','import:execute'),('analyst','pricing:read'),('analyst','analytics:read'),
            ('analyst','report:read'),('analyst','report:generate'),('analyst','comparison:read'),('analyst','member:read'),
            ('viewer','product:read'),('viewer','supplier:read'),('viewer','sales:read'),('viewer','expense:read'),
            ('viewer','import:read'),('viewer','pricing:read'),('viewer','analytics:read'),('viewer','report:read'),
            ('viewer','comparison:read'),('viewer','member:read')
        ) AS grants(role_name, permission_code)
        JOIN roles r ON r.name = grants.role_name
        JOIN permissions p ON p.code = grants.permission_code
        ON CONFLICT DO NOTHING
    """)


def downgrade() -> None:
    op.drop_index("ix_idempotency_keys_expires_at", table_name="idempotency_keys")
    op.drop_table("idempotency_keys")
    op.drop_index("ix_audit_logs_tenant_created_at", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_table("password_reset_tokens")
    op.drop_index("ix_sessions_idle_expires_at", table_name="sessions")
    op.drop_table("sessions")
    op.drop_table("role_permissions")
    op.drop_table("memberships")
    op.drop_table("tenant_settings")
    op.drop_table("users")
    op.drop_table("permissions")
    op.drop_table("roles")
    op.drop_table("tenants")
