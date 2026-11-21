"""MarginPilot FastAPI application factory with identity, tenancy, catalog and import APIs.

Startup is fail-fast: invalid configuration raises before serving traffic.
Database schema changes are applied only through explicit Alembic migrations.
"""

import re
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1 import health
from app.core.config import get_settings
from app.core.errors import error_response, validation_details
from app.core.logging import configure_logging, logger
from app.core.middleware import (
    GlobalExceptionHandlerMiddleware,
    RequestContextMiddleware,
    UploadBodyLimitMiddleware,
)
from app.modules.analytics.router import router as analytics_router
from app.modules.catalog.router import router as catalog_router
from app.modules.comparison.router import router as comparison_router
from app.modules.expenses.router import router as expenses_router
from app.modules.identity.router import router as identity_router
from app.modules.imports.router import router as imports_router
from app.modules.pricing.router import router as pricing_router
from app.modules.sales.router import router as sales_router
from app.modules.tenancy.router import router as tenancy_router


def create_app() -> FastAPI:
    settings = get_settings()  # fail-fast: raises on invalid environment
    configure_logging(settings)
    logger.info(
        "event=app_starting app_env=%s log_format=%s", settings.app_env, settings.log_format
    )

    # Security.md A05: API docs are disabled outside development/staging.
    expose_docs = settings.app_env != "production"
    application = FastAPI(
        title="MarginPilot API",
        version="0.1.0",
        docs_url="/api/docs" if expose_docs else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if expose_docs else None,
    )

    # Middleware order (P1-03). Starlette adds each new middleware OUTSIDE
    # the previous ones, so the calls below produce, outermost -> innermost:
    #   RequestContext -> CORS -> GlobalExceptionHandler -> UploadBodyLimit -> routes
    # RequestContext MUST stay outermost of these layers: it owns the request_id
    # (contextvar + X-Request-ID header + access log + security headers), so
    # even a response produced by GlobalExceptionHandlerMiddleware — i.e. an
    # unexpected 500 — still carries X-Request-ID, the security headers and
    # the correlated access-log entry. Do not reorder these four calls.
    application.add_middleware(
        UploadBodyLimitMiddleware, max_bytes=settings.upload_max_mb * 1024 * 1024
    )
    application.add_middleware(GlobalExceptionHandlerMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "X-Request-ID", "X-CSRF-Token", "Idempotency-Key"],
        expose_headers=["X-CSRF-Token", "X-Request-ID"],
    )
    application.add_middleware(RequestContextMiddleware)

    application.include_router(health.router)
    application.include_router(analytics_router, prefix="/api/v1")
    application.include_router(identity_router, prefix="/api/v1")
    application.include_router(tenancy_router, prefix="/api/v1")
    application.include_router(catalog_router, prefix="/api/v1")
    application.include_router(comparison_router, prefix="/api/v1")
    application.include_router(imports_router, prefix="/api/v1")
    application.include_router(sales_router, prefix="/api/v1")
    application.include_router(expenses_router, prefix="/api/v1")
    application.include_router(pricing_router, prefix="/api/v1")

    @application.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> Any:
        mapping = {
            400: ("VALIDATION_ERROR", "The request could not be processed."),
            401: ("AUTH_REQUIRED", "Authentication is required."),
            403: ("PERMISSION_DENIED", "The operation is not permitted."),
            404: ("NOT_FOUND", "The requested resource was not found."),
            409: ("CONFLICT", "The request conflicts with the current state."),
            422: ("REQUEST_INVALID", "The request data is invalid."),
            429: ("RATE_LIMITED", "Too many requests."),
        }
        code, message = mapping.get(exc.status_code, ("REQUEST_INVALID", "The request is invalid."))
        if isinstance(exc.detail, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{1,79}", exc.detail):
            code = exc.detail
        result = error_response(request, exc.status_code, code, message)
        if exc.headers:
            for header, value in exc.headers.items():
                result.headers[header] = value
        return result

    @application.exception_handler(RequestValidationError)
    async def request_validation_handler(request: Request, exc: RequestValidationError) -> Any:
        return error_response(
            request,
            status_code=422,
            code="REQUEST_INVALID",
            message="اعتبارسنجی درخواست ناموفق بود.",
            details=validation_details(exc.errors()),
        )

    return application


app = create_app()
