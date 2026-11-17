"""Integration: REAL PostgreSQL readiness (no SQLite, no mocks).

Run explicitly with:  pytest -m integration
Requires DATABASE_URL pointing at a running PostgreSQL (CI service or local
compose). Migrations/create_all are NOT run — the schema arrives in Phase 3.
"""

import os

import pytest
from fastapi.testclient import TestClient

from app.core.db import check_database_connection
from app.main import app

pytestmark = pytest.mark.integration

client = TestClient(app)


@pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not configured"
)
class TestRealPostgresReadiness:
    def test_direct_select_one_succeeds(self) -> None:
        assert check_database_connection() is True

    def test_ready_endpoint_reports_ok(self) -> None:
        response = client.get("/health/ready")
        assert response.status_code == 200
        assert response.json() == {"status": "ready", "checks": {"database": "ok"}}

    def test_live_still_ignores_database(self) -> None:
        assert client.get("/health/live").status_code == 200
