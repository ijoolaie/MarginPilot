"""MarginPilot FastAPI application factory (Phase 2 / Step 1).

Scope of this step: config, engine, structured logging, request-id and
security-header middleware, unified error handling, health endpoints.
No auth, no tenant context, no domain modules — per the Phase 2 constraints.

Startup is fail-fast: invalid configuration raises before serving traffic.
"""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1 import health
from app.core.config import get_settings
from app.core.errors import error_response, validation_details
from app.core.logging import configure_logging, logger
from app.core.middleware import GlobalExceptionHandlerMiddleware, RequestContextMiddleware


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
    #   RequestContext -> CORS -> GlobalExceptionHandler -> routes
    # RequestContext MUST stay outermost of the three: it owns the request_id
    # (contextvar + X-Request-ID header + access log + security headers), so
    # even a response produced by GlobalExceptionHandlerMiddleware — i.e. an
    # unexpected 500 — still carries X-Request-ID, the security headers and
    # the correlated access-log entry. Do not reorder these three calls.
    application.add_middleware(GlobalExceptionHandlerMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "X-Request-ID", "X-CSRF-Token"],
    )
    application.add_middleware(RequestContextMiddleware)

    application.include_router(health.router)

    @application.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> Any:
        mapping = {
            401: ("AUTH_REQUIRED", "احراز هویت لازم است."),
            403: ("PERMISSION_DENIED", "شما اجازهٔ انجام این عملیات را ندارید."),
            404: ("NOT_FOUND", "منبع یافت نشد."),
            409: ("CONFLICT", "درخواست با وضعیت فعلی منبع در تعارض است."),
        }
        code, message = mapping.get(exc.status_code, ("REQUEST_INVALID", str(exc.detail)))
        return error_response(request, exc.status_code, code, message)

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
