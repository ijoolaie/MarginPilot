"""Unit tests: health endpoints, request-id propagation, security headers."""

import asyncio
import time
import uuid

import pytest
from fastapi.testclient import TestClient
from httpx2 import ASGITransport, AsyncClient

import app.api.v1.health as health_module
from app.core.db import check_database_connection  # noqa: F401  (monkeypatch target ref)
from app.main import app

client = TestClient(app)


class TestLive:
    def test_live_returns_200_without_database(self) -> None:
        response = client.get("/health/live")
        assert response.status_code == 200
        assert response.json() == {"status": "alive"}

    def test_live_carries_request_id(self) -> None:
        response = client.get("/health/live")
        request_id = response.headers["X-Request-ID"]
        assert uuid.UUID(hex=request_id)  # valid UUID hex, 32 chars

    def test_security_headers_present(self) -> None:
        response = client.get("/health/live")
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
        assert "default-src 'self'" in response.headers["Content-Security-Policy"]


class TestReady:
    def test_ready_success_returns_200(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(health_module, "check_database_connection", lambda: True)
        response = client.get("/health/ready")
        assert response.status_code == 200
        assert response.json() == {"status": "ready", "checks": {"database": "ok"}}

    def test_ready_failure_returns_503_without_secrets(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(health_module, "check_database_connection", lambda: False)
        response = client.get("/health/ready")
        assert response.status_code == 503
        body = response.json()
        assert body == {"status": "unavailable", "checks": {"database": "failed"}}
        # No DSN, host, credential or stack fragment may leak into the body.
        body_text = str(body)
        assert "placeholder" not in body_text
        assert "localhost" not in body_text
        assert "postgresql" not in body_text

    def test_ready_failure_when_check_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom() -> bool:
            raise RuntimeError("simulated crash")

        monkeypatch.setattr(health_module, "check_database_connection", boom)
        response = client.get("/health/ready")
        assert response.status_code == 503

    def test_real_check_function_is_used_in_module(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Guard against accidentally stubbing the real function in app wiring.
        assert health_module.check_database_connection is check_database_connection


class TestReadyDoesNotBlockEventLoop:
    """P1-04: readiness runs the sync DB check in the threadpool — a slow
    database must NOT stall the event loop, and /health/live must stay
    responsive while /health/ready is blocked on the DB."""

    @pytest.mark.asyncio
    async def test_slow_db_check_leaves_liveness_responsive(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def slow_check() -> bool:
            time.sleep(1.0)  # simulated slow/unreachable database round-trip
            return True

        monkeypatch.setattr(health_module, "check_database_connection", slow_check)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            ready_task = asyncio.create_task(ac.get("/health/ready"))
            await asyncio.sleep(0.15)  # let the readiness call enter the DB wait

            loop = asyncio.get_running_loop()
            live_started = loop.time()
            live_response = await ac.get("/health/live")
            live_elapsed = loop.time() - live_started

            ready_response = await ready_task

        assert ready_response.status_code == 200  # slow check still succeeds
        assert live_response.status_code == 200
        # If readiness ran on the event loop, liveness could only complete
        # after the 1.0s sleep — well above this threshold.
        assert live_elapsed < 0.7, f"event loop was blocked for {live_elapsed:.2f}s"
