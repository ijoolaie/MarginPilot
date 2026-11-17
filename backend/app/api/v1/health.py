"""Health endpoints (Phase 2 / Step 1).

- GET /health/live  -> process liveness only; NEVER touches the database.
- GET /health/ready -> real PostgreSQL connectivity via `SELECT 1`;
  503 with a stable body on failure; no DSN/host/credential in responses.
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.db import check_database_connection

router = APIRouter(tags=["health"])


@router.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "alive"}


@router.get("/health/ready")
def ready() -> JSONResponse:
    # Sync handler on purpose (P1-04): check_database_connection() is a
    # blocking (sync) DB round-trip. FastAPI runs sync handlers in the
    # threadpool, so a slow or unreachable database CANNOT stall the event
    # loop — /health/live stays responsive meanwhile (tested). An async def
    # here would run the blocking call on the loop itself and freeze every
    # concurrent request, including liveness.
    #
    # Readiness must degrade to 503 on ANY failure — never a 500.
    try:
        database_ok = check_database_connection()
    except Exception:  # noqa: BLE001
        database_ok = False
    if database_ok:
        ok = {"status": "ready", "checks": {"database": "ok"}}
        return JSONResponse(status_code=200, content=ok)
    failed = {"status": "unavailable", "checks": {"database": "failed"}}
    return JSONResponse(
        status_code=503,
        content=failed,
        headers={"Retry-After": "5"},
    )
