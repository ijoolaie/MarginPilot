"""Structured logging — JSON by default (architecture.md §7).

Log record fields: ts, level, logger, event, request_id, plus whitelisted
request fields on access-log events. Sensitive data (passwords, tokens,
cookies, PII) is never passed to loggers, AND — as defence in depth (P2-05)
— every formatter scrubs its final output (message + formatted traceback)
against the configured secret fragments (DATABASE_URL, its password
component, and the URL-decoded form of that password), replacing them with
[REDACTED]. SQLAlchemy exceptions can embed the connection DSN in their
text, so scrubbing happens at the last possible point, for every record,
regardless of which module logged it. request_id correlation is unaffected.
"""

import logging
import sys
from collections.abc import Sequence
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any
from urllib.parse import unquote, urlsplit

from app.core.config import Settings

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

logger = logging.getLogger("marginpilot.app")

ACCESS_LOG_FIELDS = ("method", "path", "status", "duration_ms", "user_id", "tenant_id")

REDACTED = "[REDACTED]"


def redact_secrets(text: str, secrets: Sequence[str]) -> str:
    """Replace every secret fragment in `text` with [REDACTED]."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, REDACTED)
    return text


def secret_fragments(settings: Settings) -> tuple[str, ...]:
    """Fragments that must never appear in logs (P2-05): the full DSN, its
    password component as written in the URL (percent-encoded), and the
    URL-decoded form of that password. Exception text may embed any of these
    shapes — SQLAlchemy/pysycopg messages usually quote the DSN verbatim,
    while driver/auth messages can carry the decoded password — so every
    distinct non-empty shape is scrubbed. A password without %-escapes
    decodes to itself and a duplicate is never added; empty candidates are
    skipped as well."""
    fragments: list[str] = [settings.database_url]
    password = urlsplit(settings.database_url).password
    for candidate in (password, unquote(password) if password else ""):
        if candidate and candidate not in fragments:
            fragments.append(candidate)
    return tuple(fragments)


class JsonFormatter(logging.Formatter):
    """Minimal dependency-free JSON formatter with UTC ISO-8601 timestamps."""

    def __init__(self, secrets: Sequence[str] = ()) -> None:
        super().__init__()
        self._secrets = tuple(secrets)

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "event": redact_secrets(record.getMessage(), self._secrets),
            "request_id": request_id_var.get(),
        }
        # Whitelisted structured fields, when present on the record.
        for field in ACCESS_LOG_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exc_info"] = redact_secrets(
                self.formatException(record.exc_info), self._secrets
            )
        return _dumps(payload)


def _dumps(payload: dict[str, Any]) -> str:
    import json

    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


class ConsoleFormatter(logging.Formatter):
    """Human-readable formatter for local development only."""

    def __init__(self, secrets: Sequence[str] = ()) -> None:
        super().__init__()
        self._secrets = tuple(secrets)

    def format(self, record: logging.LogRecord) -> str:
        request_id = request_id_var.get() or "-"
        base = (
            f"{datetime.now(UTC).isoformat(timespec='seconds')} "
            f"{record.levelname:<8} [{request_id}] {record.name}: "
            f"{redact_secrets(record.getMessage(), self._secrets)}"
        )
        if record.exc_info:
            base += "\n" + redact_secrets(self.formatException(record.exc_info), self._secrets)
        return base


def configure_logging(settings: Settings) -> None:
    """Idempotently install the root handler matching LOG_LEVEL / LOG_FORMAT."""
    secrets = secret_fragments(settings)
    formatter: logging.Formatter
    if settings.log_format == "json":
        formatter = JsonFormatter(secrets)
    else:
        formatter = ConsoleFormatter(secrets)
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(settings.log_level)
    root.handlers.clear()
    root.addHandler(handler)

    # Uvicorn loggers flow through the root handler for uniform output.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
