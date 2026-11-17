"""Unified error response schema (api-contract.md §2).

{
  "error": {"code": ..., "message": ..., "details": [...], "request_id": ...}
}

Internal exception details NEVER reach the client — they go to the log with
the request_id only (architecture.md §2 step 10).
"""

from collections.abc import Sequence
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.core.logging import request_id_var


class ErrorDetail(BaseModel):
    field: str | None = None
    issue: str


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[ErrorDetail] = Field(default_factory=list)
    request_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


def error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: list[ErrorDetail] | None = None,
) -> JSONResponse:
    """Build the unified error response with the current request_id attached."""
    body = ErrorResponse(
        error=ErrorBody(
            code=code,
            message=message,
            details=details or [],
            request_id=request_id_var.get(),
        )
    )
    return JSONResponse(status_code=status_code, content=body.model_dump())


def validation_details(raw_errors: Sequence[dict[str, Any]]) -> list[ErrorDetail]:
    """Map pydantic/FastAPI validation errors onto the unified detail shape."""
    details: list[ErrorDetail] = []
    for err in raw_errors:
        loc = ".".join(str(part) for part in err.get("loc", ()) if part != "body")
        details.append(ErrorDetail(field=loc or None, issue=err.get("msg", "invalid value")))
    return details
