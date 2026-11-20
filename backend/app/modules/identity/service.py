"""Identity-domain service primitives that do not depend on HTTP delivery."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.modules.identity.models import PasswordResetToken
from app.modules.identity.security import new_opaque_token, token_digest


def create_password_reset_token(db: OrmSession, user_id: int, lifetime_minutes: int = 30) -> str:
    """Persist a one-time reset-token digest and return the raw value to trusted delivery code."""
    if lifetime_minutes < 1 or lifetime_minutes > 1440:
        raise ValueError("Password reset token lifetime must be between 1 and 1440 minutes.")
    raw_token = new_opaque_token()
    db.add(
        PasswordResetToken(
            user_id=user_id,
            token_hash=token_digest(raw_token),
            expires_at=datetime.now(UTC) + timedelta(minutes=lifetime_minutes),
        )
    )
    db.flush()
    return raw_token


def consume_password_reset_token(db: OrmSession, raw_token: str) -> int | None:
    """Atomically mark a valid, unexpired token as consumed; caller commits with password update."""
    now = datetime.now(UTC)
    record = db.scalar(
        select(PasswordResetToken)
        .where(
            PasswordResetToken.token_hash == token_digest(raw_token),
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at > now,
        )
        .with_for_update()
    )
    if record is None:
        return None
    record.used_at = now
    return record.user_id
