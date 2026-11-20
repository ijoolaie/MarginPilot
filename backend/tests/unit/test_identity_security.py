from __future__ import annotations

from fastapi import Request

from app.core.config import Settings
from app.modules.identity.rate_limit import InMemoryRateLimiter
from app.modules.identity.router import _origin_allowed
from app.modules.identity.security import (
    constant_time_digest_match,
    hash_password,
    new_opaque_token,
    password_hash_needs_rehash,
    token_digest,
    validate_password,
    verify_password,
)


def test_argon2id_password_hash_and_verification() -> None:
    password = "correct horse battery staple 2026"
    encoded = hash_password(password)
    assert encoded.startswith("$argon2id$")
    assert verify_password(password, encoded)
    assert not verify_password("wrong password", encoded)
    assert not password_hash_needs_rehash(encoded)


def test_password_policy_rejects_short_and_oversized_values() -> None:
    for password in ("short", "x" * 129):
        try:
            validate_password(password)
        except ValueError:
            pass
        else:
            raise AssertionError("password policy accepted an invalid password")


def test_opaque_tokens_are_random_and_only_digest_is_stored() -> None:
    first = new_opaque_token()
    second = new_opaque_token()
    assert first != second
    assert len(first) >= 40
    digest = token_digest(first)
    assert first not in digest
    assert constant_time_digest_match(first, digest)
    assert not constant_time_digest_match(second, digest)


def test_rate_limiter_enforces_window_and_resets() -> None:
    limiter = InMemoryRateLimiter()
    assert limiter.check("ip:email", limit=2, window_seconds=60) == 0
    assert limiter.check("ip:email", limit=2, window_seconds=60) == 0
    assert limiter.check("ip:email", limit=2, window_seconds=60) > 0
    limiter.clear()
    assert limiter.check("ip:email", limit=2, window_seconds=60) == 0


def _request(headers: list[tuple[bytes, bytes]]) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/auth/login",
            "headers": headers,
            "client": ("127.0.0.1", 12345),
            "server": ("test", 80),
            "scheme": "http",
            "query_string": b"",
        }
    )


def test_origin_and_referer_must_match_exact_allowlist_origin() -> None:
    settings = Settings(
        database_url="postgresql+psycopg://user:pass@localhost/db",
        cors_origins=["https://app.example.test"],
    )
    assert _origin_allowed(_request([(b"origin", b"https://app.example.test")]), settings)
    assert _origin_allowed(_request([(b"referer", b"https://app.example.test/login")]), settings)
    assert not _origin_allowed(_request([(b"origin", b"https://evil.example.test")]), settings)
    assert not _origin_allowed(_request([]), settings)
