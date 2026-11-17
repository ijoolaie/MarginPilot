"""Unit tests: engine construction — psycopg-only dialect, no psycopg2
fallback (P1-02). No network: engines are created but never connected."""

import pytest
from sqlalchemy.engine import Engine

from app.core.config import Settings
from app.core.db import build_engine

VALID_URL = "postgresql+psycopg://marginpilot:secret@localhost:5432/marginpilot"


class TestEngineDialect:
    def test_engine_resolves_to_psycopg3_dialect(self) -> None:
        engine: Engine = build_engine(Settings(database_url=VALID_URL))
        try:
            # The resolved DBAPI driver must be psycopg (3) — never psycopg2.
            assert engine.dialect.driver == "psycopg"
            assert engine.dialect.name == "postgresql"
            assert engine.url.drivername == "postgresql+psycopg"
        finally:
            engine.dispose()

    def test_engine_rejects_bare_postgresql_scheme(self) -> None:
        # Defence in depth: even a Settings instance that bypassed validation
        # (model_construct) must be stopped by the engine guard.
        unvalidated = Settings.model_construct(
            database_url="postgresql://marginpilot:secret@localhost:5432/marginpilot"
        )
        with pytest.raises(ValueError, match="postgresql\\+psycopg"):
            build_engine(unvalidated)

    def test_engine_rejects_other_dialects(self) -> None:
        unvalidated = Settings.model_construct(
            database_url="postgresql+psycopg2://marginpilot:secret@localhost:5432/marginpilot"
        )
        with pytest.raises(ValueError, match="postgresql\\+psycopg"):
            build_engine(unvalidated)
