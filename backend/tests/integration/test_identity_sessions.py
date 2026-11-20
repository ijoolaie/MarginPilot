from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.core.db import get_engine
from app.main import app
from app.modules.identity.models import Session as IdentitySession
from app.modules.identity.models import User
from app.modules.identity.rate_limit import login_limiter
from app.modules.identity.security import hash_password, verify_password
from app.modules.identity.service import consume_password_reset_token, create_password_reset_token

pytestmark = pytest.mark.integration
PASSWORD = "correct horse battery staple 2026"
ORIGIN = "http://localhost:3000"


def _create_user() -> User:
    with OrmSession(get_engine()) as db:
        user = User(
            email=f"auth-{uuid.uuid4().hex}@example.test",
            password_hash=hash_password(PASSWORD),
            full_name="Integration User",
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user


def _login(client: TestClient, email: str):
    return client.post(
        "/api/v1/auth/login",
        headers={"Origin": ORIGIN},
        json={"email": email, "password": PASSWORD},
    )


def test_login_session_csrf_me_and_logout_round_trip() -> None:
    user = _create_user()
    with TestClient(app, base_url=ORIGIN) as client:
        response = _login(client, user.email)
        assert response.status_code == 200
        assert response.headers["x-csrf-token"]
        assert "httponly" in response.headers["set-cookie"].lower()
        assert "samesite=lax" in response.headers["set-cookie"].lower()
        raw_session_token = client.cookies.get("mp_session")
        assert raw_session_token

        with OrmSession(get_engine()) as db:
            session = db.scalar(select(IdentitySession).where(IdentitySession.user_id == user.id))
            assert session is not None
            assert session.token_hash == hashlib.sha256(raw_session_token.encode()).hexdigest()
            assert raw_session_token not in session.token_hash
            assert session.revoked_at is None

        missing_origin = client.get("/api/v1/auth/me")
        assert missing_origin.status_code == 403
        me = client.get("/api/v1/auth/me", headers={"Origin": ORIGIN})
        assert me.status_code == 200
        assert me.json()["user"]["id"] == user.id
        csrf = me.headers["x-csrf-token"]
        assert csrf

        denied = client.post("/api/v1/auth/logout", headers={"Origin": ORIGIN})
        assert denied.status_code == 403

        logout = client.post(
            "/api/v1/auth/logout",
            headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
        )
        assert logout.status_code == 204

        after_logout = client.get("/api/v1/auth/me")
        assert after_logout.status_code == 401


def test_login_rejects_missing_or_untrusted_origin() -> None:
    user = _create_user()
    with TestClient(app, base_url=ORIGIN) as client:
        missing = client.post(
            "/api/v1/auth/login", json={"email": user.email, "password": PASSWORD}
        )
        assert missing.status_code == 403
        untrusted = client.post(
            "/api/v1/auth/login",
            headers={"Origin": "https://attacker.example"},
            json={"email": user.email, "password": PASSWORD},
        )
        assert untrusted.status_code == 403
        assert untrusted.json()["error"]["code"] == "CSRF_ORIGIN_REJECTED"


def test_password_change_revokes_all_existing_sessions() -> None:
    user = _create_user()
    with TestClient(app, base_url=ORIGIN) as client:
        first = _login(client, user.email)
        assert first.status_code == 200
        csrf = first.headers["x-csrf-token"]
        second_client = TestClient(app, base_url=ORIGIN)
        try:
            second = _login(second_client, user.email)
            assert second.status_code == 200
            response = client.post(
                "/api/v1/auth/password/change",
                headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
                json={
                    "current_password": PASSWORD,
                    "new_password": "new correct horse battery staple",
                },
            )
            assert response.status_code == 204
            assert client.get("/api/v1/auth/me").status_code == 401
            assert second_client.get("/api/v1/auth/me").status_code == 401
            with OrmSession(get_engine()) as db:
                active_sessions = db.scalars(
                    select(IdentitySession).where(
                        IdentitySession.user_id == user.id,
                        IdentitySession.revoked_at.is_(None),
                    )
                ).all()
                assert active_sessions == []
                updated_user = db.get(User, user.id)
                assert updated_user is not None
                assert verify_password(
                    "new correct horse battery staple", updated_user.password_hash
                )
        finally:
            second_client.close()


def test_account_lockout_after_configured_failed_attempts() -> None:
    user = _create_user()
    login_limiter.clear()
    with TestClient(app, base_url=ORIGIN) as client:
        for attempt in range(10):
            response = client.post(
                "/api/v1/auth/login",
                headers={"Origin": ORIGIN},
                json={"email": user.email, "password": "incorrect password"},
            )
            if attempt < 9:
                assert response.status_code == 401
                login_limiter.clear()
            else:
                assert response.status_code == 429
                assert response.headers["retry-after"]
                assert response.json()["error"]["code"] == "ACCOUNT_TEMPORARILY_LOCKED"
        locked = _login(client, user.email)
        assert locked.status_code == 429


def test_expired_idle_session_is_rejected() -> None:
    user = _create_user()
    with TestClient(app, base_url=ORIGIN) as client:
        response = _login(client, user.email)
        assert response.status_code == 200
        with OrmSession(get_engine()) as db:
            session = db.scalar(select(IdentitySession).where(IdentitySession.user_id == user.id))
            assert session is not None
            session.idle_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            db.commit()
        assert client.get("/api/v1/auth/me").status_code == 401


def test_password_reset_token_is_single_use_and_only_digest_is_persisted() -> None:
    user = _create_user()
    with OrmSession(get_engine()) as db:
        raw_token = create_password_reset_token(db, user.id)
        db.commit()
        from app.modules.identity.models import PasswordResetToken

        record = db.scalar(select(PasswordResetToken).where(PasswordResetToken.user_id == user.id))
        assert record is not None
        assert raw_token not in record.token_hash
        assert record.token_hash == hashlib.sha256(raw_token.encode()).hexdigest()
        assert consume_password_reset_token(db, raw_token) == user.id
        db.commit()
        assert consume_password_reset_token(db, raw_token) is None


def test_user_can_revoke_another_session_with_csrf() -> None:
    user = _create_user()
    with TestClient(app, base_url=ORIGIN) as first_client:
        first = _login(first_client, user.email)
        assert first.status_code == 200
        csrf = first.headers["x-csrf-token"]
        with TestClient(app, base_url=ORIGIN) as second_client:
            second = _login(second_client, user.email)
            assert second.status_code == 200
            sessions = first_client.get("/api/v1/auth/sessions")
            assert sessions.status_code == 200
            data = sessions.json()["data"]
            assert len(data) == 2
            other_session = next(item for item in data if not item["current"])
            revoked = first_client.delete(
                f"/api/v1/auth/sessions/{other_session['id']}",
                headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
            )
            assert revoked.status_code == 204
            assert second_client.get("/api/v1/auth/me").status_code == 401
