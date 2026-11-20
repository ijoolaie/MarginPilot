"""Alembic environment bound to validated application database settings."""

from logging.config import fileConfig

from alembic import context

from app.core.config import get_settings
from app.core.db import build_engine
from app.core.models import Base
from app.modules.audit import models as audit_models  # noqa: F401
from app.modules.catalog import models as catalog_models  # noqa: F401
from app.modules.comparison import models as comparison_models  # noqa: F401
from app.modules.expenses import models as expense_models  # noqa: F401
from app.modules.identity import models as identity_models  # noqa: F401
from app.modules.imports import models as import_models  # noqa: F401
from app.modules.sales import models as sales_models  # noqa: F401
from app.modules.tenancy import models as tenancy_models  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = build_engine(settings)
    try:
        with connectable.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
                compare_server_default=True,
                transaction_per_migration=True,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
