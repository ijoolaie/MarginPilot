"""Password and opaque-token primitives for the identity module."""

from __future__ import annotations

import hashlib
import secrets
from typing import Final

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_PASSWORD_HASHER: Final = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)
_DUMMY_PASSWORD_HASH: Final = _PASSWORD_HASHER.hash(secrets.token_urlsafe(32))


def hash_password(password: str) -> str:
    """Hash a password using Argon2id with explicit, reviewed work factors."""
    validate_password(password)
    return _PASSWORD_HASHER.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify safely; malformed stored hashes are treated as authentication failure."""
    try:
        return _PASSWORD_HASHER.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_hash_needs_rehash(password_hash: str) -> bool:
    try:
        return _PASSWORD_HASHER.check_needs_rehash(password_hash)
    except (VerificationError, InvalidHashError):
        return True


def validate_password(password: str) -> None:
    if len(password) < 12 or len(password) > 128:
        raise ValueError("Password must contain between 12 and 128 characters.")


def new_opaque_token() -> str:
    """Return 256 bits of CSPRNG entropy encoded for HTTP transport."""
    return secrets.token_urlsafe(32)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def constant_time_digest_match(token: str, expected_digest: str) -> bool:
    import hmac

    return hmac.compare_digest(token_digest(token), expected_digest)


def verify_unknown_user_password(password: str) -> None:
    """Burn the same Argon2 work factor when an email does not exist."""
    verify_password(password, _DUMMY_PASSWORD_HASH)
