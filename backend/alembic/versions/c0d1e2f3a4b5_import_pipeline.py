"""Add tenant-scoped two-phase import batches and rows."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c0d1e2f3a4b5"
down_revision: str | None = "a7c19d4e6f20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "imports",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("file_hash", sa.String(64), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("mime_type", sa.String(128), nullable=False),
        sa.Column("sheet_name", sa.String(128)),
        sa.Column("column_headers", postgresql.JSONB(), nullable=False),
        sa.Column(
            "mapping", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "stats", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("supplier_id", sa.BigInteger()),
        sa.Column("price_list_title", sa.String(200)),
        sa.Column("received_at", sa.Date()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="CASCADE", name="fk_imports_tenant"
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], ondelete="RESTRICT", name="fk_imports_creator"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "supplier_id"],
            ["suppliers.tenant_id", "suppliers.id"],
            ondelete="RESTRICT",
            name="fk_imports_supplier_tenant",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_imports_tenant_id"),
        sa.CheckConstraint(
            "kind IN ('products', 'supplier_prices', 'sales')", name=op.f("ck_imports_kind_allowed")
        ),
        sa.CheckConstraint(
            "status IN ('uploaded', 'parsed', 'mapped', 'validated', "
            "'awaiting_confirmation', 'committed', 'failed', 'cancelled')",
            name=op.f("ck_imports_status_allowed"),
        ),
        sa.CheckConstraint("file_size_bytes > 0", name=op.f("ck_imports_file_size_positive")),
        sa.CheckConstraint(
            "length(btrim(file_name)) > 0", name=op.f("ck_imports_file_name_not_blank")
        ),
        sa.CheckConstraint(
            "file_hash ~ '^[0-9a-f]{64}$'", name=op.f("ck_imports_file_hash_sha256")
        ),
        sa.CheckConstraint(
            "(kind = 'supplier_prices') = (supplier_id IS NOT NULL)",
            name=op.f("ck_imports_supplier_required_for_price_import"),
        ),
        sa.CheckConstraint(
            "kind <> 'supplier_prices' OR "
            "(price_list_title IS NOT NULL AND received_at IS NOT NULL)",
            name=op.f("ck_imports_price_list_metadata_required"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(column_headers) = 'array'", name=op.f("ck_imports_headers_array")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(mapping) = 'object'", name=op.f("ck_imports_mapping_object")
        ),
        sa.CheckConstraint("jsonb_typeof(stats) = 'object'", name=op.f("ck_imports_stats_object")),
    )
    op.create_index("ix_imports_tenant_created_at", "imports", ["tenant_id", "created_at"])
    op.create_index("ix_imports_tenant_status", "imports", ["tenant_id", "status"])

    op.create_table(
        "import_rows",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("import_id", sa.BigInteger(), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("raw", postgresql.JSONB(), nullable=False),
        sa.Column("normalized", postgresql.JSONB()),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'pending'")),
        sa.Column(
            "errors", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="CASCADE", name="fk_import_rows_tenant"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "import_id"],
            ["imports.tenant_id", "imports.id"],
            ondelete="CASCADE",
            name="fk_import_rows_import_tenant",
        ),
        sa.UniqueConstraint(
            "tenant_id", "import_id", "row_number", name="uq_import_rows_tenant_import_row"
        ),
        sa.CheckConstraint("row_number > 1", name=op.f("ck_import_rows_row_number_after_header")),
        sa.CheckConstraint(
            "status IN ('pending', 'valid', 'error', 'warning', 'duplicate')",
            name=op.f("ck_import_rows_status_allowed"),
        ),
        sa.CheckConstraint("jsonb_typeof(raw) = 'object'", name=op.f("ck_import_rows_raw_object")),
        sa.CheckConstraint(
            "normalized IS NULL OR jsonb_typeof(normalized) = 'object'",
            name=op.f("ck_import_rows_normalized_object"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(errors) = 'array'", name=op.f("ck_import_rows_errors_array")
        ),
    )
    op.create_index(
        "ix_import_rows_import_status", "import_rows", ["tenant_id", "import_id", "status"]
    )


def downgrade() -> None:
    op.drop_index("ix_import_rows_import_status", table_name="import_rows")
    op.drop_table("import_rows")
    op.drop_index("ix_imports_tenant_status", table_name="imports")
    op.drop_index("ix_imports_tenant_created_at", table_name="imports")
    op.drop_table("imports")
