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
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

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


class UploadBodyLimitMiddleware:
    """Reject oversized multipart uploads before Starlette spools file parts."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_request_bytes = max_bytes + 128 * 1024

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope.get("type") != "http"
            or scope.get("method") != "POST"
            or scope.get("path") != "/api/v1/imports"
        ):
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        content_type = headers.get(b"content-type", b"").lower()
        if not content_type.startswith(b"multipart/form-data"):
            await self.app(scope, receive, send)
            return
        raw_length = headers.get(b"content-length")
        if raw_length is not None:
            try:
                content_length = int(raw_length)
            except ValueError:
                await JSONResponse(
                    status_code=400,
                    content={
                        "error": {
                            "code": "CONTENT_LENGTH_INVALID",
                            "message": "Invalid request length.",
                            "details": [],
                            "request_id": request_id_var.get(),
                        }
                    },
                )(scope, receive, send)
                return
            if content_length > self.max_request_bytes:
                await self._too_large(scope, receive, send)
                return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message.get("type") == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_request_bytes:
                    raise _UploadBodyTooLarge
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _UploadBodyTooLarge:
            await self._too_large(scope, receive, send)

    async def _too_large(self, scope: Scope, receive: Receive, send: Send) -> None:
        await JSONResponse(
            status_code=413,
            content={
                "error": {
                    "code": "UPLOAD_TOO_LARGE",
                    "message": "The uploaded request exceeds the configured size limit.",
                    "details": [],
                    "request_id": request_id_var.get(),
                }
            },
        )(scope, receive, send)


class _UploadBodyTooLarge(Exception):
    """Internal signal used to stop multipart parsing at the request limit."""
