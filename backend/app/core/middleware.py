"""Request-ID + security-headers middleware (architecture.md §2, security.md §7).

Ordering contract (P1-03): RequestContextMiddleware MUST be added LAST via
add_middleware (i.e. outermost) — see app/main.py. If it runs inside
GlobalExceptionHandlerMiddleware, unhandled-500 responses leave the process
without X-Request-ID and security headers, and the access log loses its
status code."""

import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.errors import error_response
from app.core.logging import ACCESS_LOG_FIELDS, logger, request_id_var

SecurityHeaders = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    # Minimal baseline; CSP is tightened + tested in Phase 12 (security.md §7).
    "Content-Security-Policy": "default-src 'self'",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assigns a UUID request_id, echoes it in X-Request-ID, and emits the
    structured access log with whitelisted fields only."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = uuid.uuid4().hex
        request.state.request_id = request_id
        request_id_token = request_id_var.set(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            self._log_request(request, 500, started)
            request_id_var.reset(request_id_token)
            raise
        duration_ms = round((time.perf_counter() - started) * 1000, 1)
        self._log_request(request, response.status_code, started, duration_ms)
        request_id_var.reset(request_id_token)
        response.headers["X-Request-ID"] = request_id
        for header, value in SecurityHeaders.items():
            response.headers.setdefault(header, value)
        return response

    def _log_request(
        self, request: Request, status: int, started: float, duration_ms: float = 0.0
    ) -> None:
        extras = {
            "method": request.method,
            "path": request.url.path,
            "status": status,
            "duration_ms": duration_ms,
            # Auth/TenantContext arrive in Phase 3; keys exist per the log schema.
            "user_id": None,
            "tenant_id": None,
        }
        logger.info(
            "http_request",
            extra={key: value for key, value in extras.items() if key in ACCESS_LOG_FIELDS},
        )


class GlobalExceptionHandlerMiddleware(BaseHTTPMiddleware):
    """Last-resort handler: uniform 500 without any internal detail leak."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        try:
            return await call_next(request)
        except Exception:
            logger.exception("event=unhandled_exception")  # full detail -> log only
            return error_response(
                request,
                status_code=500,
                code="INTERNAL_ERROR",
                message="خطای داخلی سرور.",
            )
