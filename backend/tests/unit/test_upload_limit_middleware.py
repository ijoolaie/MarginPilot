from __future__ import annotations

import asyncio
import json
from typing import Any

from app.core.middleware import UploadBodyLimitMiddleware


def _run_request(
    middleware: UploadBodyLimitMiddleware, scope: dict[str, Any], body: bytes
) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []
    received = False

    async def receive() -> dict[str, Any]:
        nonlocal received
        if received:
            return {"type": "http.disconnect"}
        received = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    asyncio.run(middleware(scope, receive, send))
    return sent


def test_upload_limit_rejects_content_length_before_multipart_parser() -> None:
    called = False

    async def app(scope: Any, receive: Any, send: Any) -> None:
        nonlocal called
        called = True

    middleware = UploadBodyLimitMiddleware(app, max_bytes=10)
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/imports",
        "headers": [
            (b"content-type", b"multipart/form-data; boundary=x"),
            (b"content-length", b"200000"),
        ],
    }
    messages = _run_request(middleware, scope, b"")
    assert not called
    assert messages[0]["status"] == 413
    body = json.loads(messages[1]["body"])
    assert body["error"]["code"] == "UPLOAD_TOO_LARGE"


def test_upload_limit_stops_chunked_body_without_content_length() -> None:
    async def app(scope: Any, receive: Any, send: Any) -> None:
        while True:
            message = await receive()
            if message["type"] != "http.request" or not message.get("more_body", False):
                break

    middleware = UploadBodyLimitMiddleware(app, max_bytes=1)
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/imports",
        "headers": [(b"content-type", b"multipart/form-data; boundary=x")],
    }
    messages = _run_request(middleware, scope, b"x" * (1 + 128 * 1024 + 1))
    assert messages[0]["status"] == 413
    assert json.loads(messages[1]["body"])["error"]["code"] == "UPLOAD_TOO_LARGE"
