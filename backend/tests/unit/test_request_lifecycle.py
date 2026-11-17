"""Unit tests: unhandled-exception guarantees (P1-03) and log secret
redaction (P2-05). No network, no database."""

import json
import logging
import sys
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.logging import REDACTED, JsonFormatter, redact_secrets, secret_fragments
from app.main import app

BOOM_PATH = "/__test__/boom"
SECRET = "super-secret-db-password"
DSN = f"postgresql+psycopg://marginpilot:{SECRET}@localhost:5432/marginpilot"

# P2-05: a password written URL-encoded in the DSN (p@ss!w0rd escaped).
ENCODED_PASSWORD = "p%40ss%21w0rd"
DECODED_PASSWORD = "p@ss!w0rd"
ENCODED_DSN = (
    f"postgresql+psycopg://marginpilot:{ENCODED_PASSWORD}@localhost:5432/marginpilot"
)

client = TestClient(app)


def _boom() -> dict[str, str]:
    # Message embeds the DSN like a real SQLAlchemy exception would.
    raise RuntimeError(f"connection failed for dsn {DSN}")


@pytest.fixture()
def boom_route() -> Any:
    app.add_api_route(BOOM_PATH, _boom, methods=["GET"])
    yield
    app.router.routes = [r for r in app.router.routes if getattr(r, "path", "") != BOOM_PATH]


class TestUnhandledExceptionGuarantees:
    """P1-03: an unexpected 500 must still carry all four guarantees."""

    def test_500_carries_request_id_security_headers_and_no_leak(
        self, boom_route: Any
    ) -> None:
        response = client.get(BOOM_PATH)
        assert response.status_code == 500
        request_id = response.headers["X-Request-ID"]
        assert uuid.UUID(hex=request_id)  # header present and a valid UUID
        error = response.json()["error"]
        assert error["code"] == "INTERNAL_ERROR"
        assert error["message"] == "خطای داخلی سرور."
        # request_id non-NULL in the body and correlated with the header.
        assert error["request_id"] == request_id
        # Security headers present on the error path too.
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert "default-src 'self'" in response.headers["Content-Security-Policy"]
        assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
        # No internal exception detail leaks into the response.
        assert SECRET not in response.text
        assert DSN not in response.text
        assert "RuntimeError" not in response.text
        assert "Traceback" not in response.text

    def test_500_request_id_matches_across_header_and_body(
        self, boom_route: Any
    ) -> None:
        first = client.get(BOOM_PATH)
        second = client.get(BOOM_PATH)
        assert first.headers["X-Request-ID"] != second.headers["X-Request-ID"]
        assert first.json()["error"]["request_id"] == first.headers["X-Request-ID"]
        assert second.json()["error"]["request_id"] == second.headers["X-Request-ID"]


class TestAccessLogOn500:
    """P1-03: the access log for an unexpected 500 carries the same
    request_id; P2-05: the log (including the traceback) leaks no secrets."""

    def test_access_log_correlated_and_redacted(
        self, boom_route: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: list[str] = []

        class Capture(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                captured.append(self.format(record))

        handler = Capture()
        # The production formatter, configured with the production secret
        # fragments exactly as configure_logging() does.
        handler.setFormatter(JsonFormatter((DSN, SECRET)))
        root = logging.getLogger()
        monkeypatch.setattr(root, "handlers", [handler])

        response = client.get(BOOM_PATH)
        assert response.status_code == 500
        assert captured, "expected at least one log record"

        parsed = [json.loads(line) for line in captured if line.startswith("{")]
        access = [
            entry
            for entry in parsed
            if entry["event"] == "http_request" and entry.get("path") == BOOM_PATH
        ]
        assert access, f"access log missing for {BOOM_PATH}"
        assert access[-1]["status"] == 500
        # Same request_id as the response header (correlation holds on 500).
        assert access[-1]["request_id"] == response.headers["X-Request-ID"]

        raw = "\n".join(captured)
        # P2-05: neither the DSN nor the password may appear anywhere in the
        # log output (message or traceback), while the redaction marker and
        # request_id correlation stay visible.
        assert SECRET not in raw
        assert DSN not in raw
        assert REDACTED in raw


class TestRedactionUnit:
    """P2-05: formatter-level scrubbing, independent of the middleware."""

    def test_redact_secrets_replaces_every_fragment(self) -> None:
        text = f"auth failed: {DSN} (password {SECRET} rejected)"
        scrubbed = redact_secrets(text, (DSN, SECRET))
        assert SECRET not in scrubbed
        assert DSN not in scrubbed
        assert scrubbed.count(REDACTED) == 2

    def test_json_formatter_scrubs_message_and_traceback(self) -> None:
        formatter = JsonFormatter((DSN, SECRET))
        try:
            raise RuntimeError(f"connect to {DSN} failed")
        except RuntimeError:
            record = logging.LogRecord(
                "marginpilot.app",
                logging.ERROR,
                __file__,
                1,
                f"query failed for {DSN}",  # message embeds the DSN too
                None,
                sys.exc_info(),
            )
        output = formatter.format(record)
        payload = json.loads(output)
        assert SECRET not in output
        assert DSN not in output
        assert REDACTED in payload["event"]  # message scrubbed
        assert REDACTED in payload["exc_info"]  # traceback scrubbed
        assert payload["request_id"] is None  # contextvar default preserved

    def test_secret_fragments_include_url_decoded_password(self) -> None:
        # P2-05 (round 2): besides the raw (percent-encoded) password, the
        # URL-decoded shape must also be scrubbed. Full DSN and raw password
        # behaviour is preserved; no duplicates, no empty entries.
        settings = Settings(database_url=ENCODED_DSN)
        fragments = secret_fragments(settings)
        assert fragments[0] == ENCODED_DSN  # full DSN first, unchanged
        assert ENCODED_PASSWORD in fragments  # raw encoded shape
        assert DECODED_PASSWORD in fragments  # decoded shape added
        assert len(fragments) == 3  # no duplicates
        assert all(fragments)  # no empty fragments

    def test_secret_fragments_plain_password_no_duplicates(self) -> None:
        # Password without %-escapes decodes to itself -> NOT added twice.
        settings = Settings(database_url=DSN)
        assert secret_fragments(settings) == (DSN, SECRET)

    def test_json_formatter_scrubs_both_password_shapes(self) -> None:
        # Message carries the encoded password once and the decoded password
        # once; the raised exception (-> traceback) carries the same text.
        # Neither shape may survive in message or traceback, while the
        # [REDACTED] marker stays visible in both fields.
        formatter = JsonFormatter(secret_fragments(Settings(database_url=ENCODED_DSN)))
        message = f"auth failed: encoded={ENCODED_PASSWORD} decoded={DECODED_PASSWORD}"
        try:
            raise RuntimeError(message)
        except RuntimeError:
            record = logging.LogRecord(
                "marginpilot.app", logging.ERROR, __file__, 1, message, None, sys.exc_info()
            )
        output = formatter.format(record)
        payload = json.loads(output)
        assert ENCODED_PASSWORD not in output  # encoded shape scrubbed
        assert DECODED_PASSWORD not in output  # decoded shape scrubbed
        assert output.count(REDACTED) == 4  # 2 shapes x (message + traceback)
        assert REDACTED in payload["event"]
        assert REDACTED in payload["exc_info"]
