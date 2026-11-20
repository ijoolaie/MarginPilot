"""SQLAlchemy 2 engine + PostgreSQL connectivity check (real `SELECT 1`).

Declarative persistence models and Alembic migrations are introduced in Phase 3.
"""

import logging
from typing import Final

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import PSYCOPG_SCHEME, Settings, get_settings

logger = logging.getLogger("marginpilot.db")

_SELECT_ONE: Final = text("SELECT 1")
_CONNECT_TIMEOUT_SECONDS: Final = 5


def build_engine(settings: Settings) -> Engine:
    """Create the engine from validated settings. Raises on an invalid URL.

    P1-02 (defence in depth): Settings validation already rejects every
    non-psycopg scheme; this guard additionally makes a psycopg2 fallback
    impossible even if a future code path bypasses Settings validation
    (SQLAlchemy maps the bare postgresql:// scheme to the psycopg2 DBAPI
    when it is installed).
    """
    if not settings.database_url.startswith(PSYCOPG_SCHEME):
        raise ValueError(
            "DATABASE_URL must use the postgresql+psycopg:// scheme; "
            "psycopg2 fallback is not allowed."
        )
    return create_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,
        connect_args={"connect_timeout": _CONNECT_TIMEOUT_SECONDS},
    )


class EngineRegistry:
    """Holds the process-wide engine; rebuilt when the underlying settings change."""

    def __init__(self) -> None:
        self._engine: Engine | None = None
        self._bound_url: str | None = None

    def get(self, settings: Settings | None = None) -> Engine:
        settings = settings or get_settings()
        if self._engine is None or self._bound_url != settings.database_url:
            if self._engine is not None:
                self._engine.dispose()
            self._engine = build_engine(settings)
            self._bound_url = settings.database_url
        return self._engine

    def dispose(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
        self._engine = None
        self._bound_url = None


_registry = EngineRegistry()


def get_engine() -> Engine:
    return _registry.get()


def check_database_connection() -> bool:
    """Run a real `SELECT 1`. Returns False on any connection/query failure.

    Never raises, never logs connection details (no DSN fragments in logs).
    """
    try:
        with get_engine().connect() as connection:
            connection.execute(_SELECT_ONE)
        return True
    except SQLAlchemyError as exc:
        logger.warning("event=database_check_failed error_type=%s", type(exc).__name__)
        return False
    except Exception:  # noqa: BLE001 - readiness must degrade to 503, not 500
        logger.exception("event=database_check_unexpected_error")
        return False
