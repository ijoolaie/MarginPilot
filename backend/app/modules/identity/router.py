"""Identity and opaque-session HTTP endpoints. Registration awaits atomic tenancy creation."""

from __future__ import annotations

import logging
from collections.abc import Generator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession

from app.core.config import Settings, get_settings
from app.core.db import get_engine
from app.modules.audit.models import AuditLog
from app.modules.identity.models import Session as IdentitySession
from app.modules.identity.models import User
from app.modules.identity.rate_limit import login_limiter, registration_limiter
from app.modules.identity.security import (
    constant_time_digest_match,
    hash_password,
    new_opaque_token,
    password_hash_needs_rehash,
    token_digest,
    validate_password,
    verify_password,
    verify_unknown_user_password,
)
from app.modules.tenancy.models import Membership, Permission, Role, RolePermission, Tenant
from app.modules.tenancy.service import create_tenant

logger = logging.getLogger("marginpilot.auth")
router = APIRouter(prefix="/auth", tags=["auth"])


class LoginInput(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class RegistrationInput(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=128)
    full_name: str = Field(min_length=1, max_length=160)
    tenant_name: str = Field(min_length=2, max_length=160)
    currency_code: str = Field(default="IRT", pattern=r"^(IRT|IRR)$")

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().casefold()
        local, separator, domain = normalized.partition("@")
        if not separator or not local or not domain or "@" in domain or " " in normalized:
            raise ValueError("A valid email address is required.")
        if "." not in domain or domain.startswith(".") or domain.endswith("."):
            raise ValueError("A valid email address is required.")
        return normalized

    @field_validator("full_name", "tenant_name")
    @classmethod
    def strip_nonempty_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("This field cannot be blank.")
        return normalized


class PasswordChangeInput(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


@dataclass(frozen=True)
class AuthContext:
    db: OrmSession
    user: User
    session: IdentitySession


def get_db() -> Generator[OrmSession, None, None]:
    with OrmSession(get_engine()) as db:
        yield db


def _origin_allowed(request: Request, settings: Settings) -> bool:
    origin = request.headers.get("origin")
    referer = request.headers.get("referer")
    candidate = origin if origin is not None else referer
    if not candidate:
        return False
    try:
        parsed = urlsplit(candidate)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return False
        normalized = f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"
        allowed = set()
        for configured in settings.cors_origins:
            item = urlsplit(configured)
            if item.scheme and item.netloc:
                allowed.add(f"{item.scheme.lower()}://{item.netloc.lower()}")
        return normalized in allowed
    except ValueError:
        return False


def _require_allowed_origin(request: Request, settings: Settings) -> None:
    if not _origin_allowed(request, settings):
        raise HTTPException(status_code=403, detail="CSRF_ORIGIN_REJECTED")


def _audit(db: OrmSession, action: str, user_id: int, request: Request) -> None:
    db.add(
        AuditLog(
            user_id=user_id,
            action=action,
            entity_type="user",
            entity_id=str(user_id),
            detail={},
            ip=request.client.host if request.client else None,
        )
    )


def _set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_absolute_timeout_minutes * 60,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite=settings.session_cookie_samesite,
        path="/",
    )


def _clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite=settings.session_cookie_samesite,
    )


def require_session(
    request: Request,
    db: OrmSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AuthContext:
    raw_token = request.cookies.get(settings.session_cookie_name)
    if not raw_token:
        raise HTTPException(status_code=401, detail="AUTH_REQUIRED")
    now = datetime.now(UTC)
    session = db.scalar(
        select(IdentitySession)
        .where(IdentitySession.token_hash == token_digest(raw_token))
        .with_for_update()
    )
    if (
        session is None
        or session.revoked_at is not None
        or session.idle_expires_at <= now
        or session.absolute_expires_at <= now
    ):
        raise HTTPException(status_code=401, detail="AUTH_REQUIRED")
    user = db.get(User, session.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="AUTH_REQUIRED")
    session.last_seen_at = now
    session.idle_expires_at = min(
        now + timedelta(minutes=settings.session_idle_timeout_minutes),
        session.absolute_expires_at,
    )
    return AuthContext(db=db, user=user, session=session)


def require_csrf_session(
    request: Request,
    context: AuthContext = Depends(require_session),
    settings: Settings = Depends(get_settings),
) -> AuthContext:
    _require_allowed_origin(request, settings)
    supplied = request.headers.get("x-csrf-token", "")
    if not supplied or not constant_time_digest_match(supplied, context.session.csrf_token_hash):
        raise HTTPException(status_code=403, detail="CSRF_TOKEN_INVALID")
    return context


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(
    payload: RegistrationInput,
    request: Request,
    response: Response,
    db: OrmSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    _require_allowed_origin(request, settings)
    if not settings.allow_registration:
        raise HTTPException(status_code=403, detail="REGISTRATION_CLOSED")
    try:
        validate_password(payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="PASSWORD_POLICY_VIOLATION") from exc
    ip = request.client.host if request.client else "unknown"
    retry_after = registration_limiter.check(ip, settings.rate_limit_register_per_hour, 3600)
    if retry_after:
        raise HTTPException(
            status_code=429, detail="RATE_LIMITED", headers={"Retry-After": str(retry_after)}
        )
    email = payload.email.strip().casefold()
    if db.scalar(select(User.id).where(User.email == email)) is not None:
        raise HTTPException(status_code=409, detail="EMAIL_ALREADY_REGISTERED")
    now = datetime.now(UTC)
    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name.strip(),
        is_active=True,
    )
    db.add(user)
    db.flush()
    tenant, membership = create_tenant(
        db, user, payload.tenant_name, payload.currency_code, settings.max_tenants_per_user
    )
    raw_token = new_opaque_token()
    raw_csrf = new_opaque_token()
    absolute_expiry = now + timedelta(minutes=settings.session_absolute_timeout_minutes)
    session = IdentitySession(
        user_id=user.id,
        tenant_id=tenant.id,
        token_hash=token_digest(raw_token),
        csrf_token_hash=token_digest(raw_csrf),
        ip=ip,
        user_agent=request.headers.get("user-agent", "")[:512] or None,
        created_at=now,
        last_seen_at=now,
        idle_expires_at=min(
            now + timedelta(minutes=settings.session_idle_timeout_minutes), absolute_expiry
        ),
        absolute_expires_at=absolute_expiry,
    )
    db.add(session)
    _audit(db, "auth.register.success", user.id, request)
    db.add(
        AuditLog(
            user_id=user.id,
            tenant_id=tenant.id,
            action="tenant.created",
            entity_type="tenant",
            entity_id=str(tenant.id),
            detail={"membership_id": membership.id},
            ip=ip,
        )
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        duplicate = db.scalar(select(User.id).where(User.email == email))
        if duplicate is not None:
            raise HTTPException(status_code=409, detail="EMAIL_ALREADY_REGISTERED") from exc
        raise HTTPException(status_code=409, detail="TENANT_CREATION_CONFLICT") from exc
    _set_session_cookie(response, raw_token, settings)
    response.headers["X-CSRF-Token"] = raw_csrf
    return {
        "user": {"id": user.id, "email": user.email, "full_name": user.full_name},
        "tenant": {"id": tenant.id, "name": tenant.name, "slug": tenant.slug},
        "role": "owner",
    }


@router.post("/login")
def login(
    payload: LoginInput,
    request: Request,
    response: Response,
    db: OrmSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    _require_allowed_origin(request, settings)
    email = payload.email.strip().casefold()
    ip = request.client.host if request.client else "unknown"
    retry_after = login_limiter.check(f"{ip}:{email}", settings.rate_limit_login_per_minute, 60)
    if retry_after:
        raise HTTPException(
            status_code=429,
            detail="RATE_LIMITED",
            headers={"Retry-After": str(retry_after)},
        )

    user = db.scalar(select(User).where(User.email == email).with_for_update())
    now = datetime.now(UTC)
    if user is None:
        verify_unknown_user_password(payload.password)
        raise HTTPException(status_code=401, detail="INVALID_CREDENTIALS")
    if user.locked_until is not None and user.locked_until > now:
        retry = max(1, int((user.locked_until - now).total_seconds()))
        raise HTTPException(
            status_code=429,
            detail="ACCOUNT_TEMPORARILY_LOCKED",
            headers={"Retry-After": str(retry)},
        )
    if not user.is_active:
        verify_unknown_user_password(payload.password)
        raise HTTPException(status_code=401, detail="INVALID_CREDENTIALS")
    if not verify_password(payload.password, user.password_hash):
        if user.locked_until is not None and user.locked_until <= now:
            user.failed_login_count = 0
            user.locked_until = None
        user.failed_login_count += 1
        if user.failed_login_count >= settings.login_lockout_threshold:
            user.locked_until = now + timedelta(minutes=settings.login_lockout_minutes)
        _audit(db, "auth.login.failed", user.id, request)
        db.commit()
        if user.locked_until is not None:
            retry = settings.login_lockout_minutes * 60
            raise HTTPException(
                status_code=429,
                detail="ACCOUNT_TEMPORARILY_LOCKED",
                headers={"Retry-After": str(retry)},
            )
        raise HTTPException(status_code=401, detail="INVALID_CREDENTIALS")

    user.failed_login_count = 0
    user.locked_until = None
    if password_hash_needs_rehash(user.password_hash):
        user.password_hash = hash_password(payload.password)
    raw_token = new_opaque_token()
    raw_csrf = new_opaque_token()
    absolute_expiry = now + timedelta(minutes=settings.session_absolute_timeout_minutes)
    session = IdentitySession(
        user_id=user.id,
        tenant_id=None,
        token_hash=token_digest(raw_token),
        csrf_token_hash=token_digest(raw_csrf),
        ip=ip,
        user_agent=request.headers.get("user-agent", "")[:512] or None,
        created_at=now,
        last_seen_at=now,
        idle_expires_at=min(
            now + timedelta(minutes=settings.session_idle_timeout_minutes), absolute_expiry
        ),
        absolute_expires_at=absolute_expiry,
    )
    db.add(session)
    _audit(db, "auth.login.success", user.id, request)
    db.commit()
    _set_session_cookie(response, raw_token, settings)
    response.headers["X-CSRF-Token"] = raw_csrf
    return {"user": {"id": user.id, "email": user.email, "full_name": user.full_name}}


@router.get("/me")
def me(
    request: Request,
    response: Response,
    context: AuthContext = Depends(require_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    # This GET rotates CSRF state, so it also requires a trusted browser origin.
    _require_allowed_origin(request, settings)
    # CSRF material is deliberately rotated: only its SHA-256 digest is persisted.
    raw_csrf = new_opaque_token()
    context.session.csrf_token_hash = token_digest(raw_csrf)
    memberships = context.db.execute(
        select(Membership, Tenant, Role)
        .join(Tenant, Tenant.id == Membership.tenant_id)
        .join(Role, Role.id == Membership.role_id)
        .where(
            Membership.user_id == context.user.id,
            Membership.status == "active",
            Tenant.status == "active",
            Tenant.deleted_at.is_(None),
        )
        .order_by(Tenant.id)
    ).all()
    active_tenant: dict[str, object] | None = None
    if context.session.tenant_id is not None:
        active_row = next(
            (row for row in memberships if row[1].id == context.session.tenant_id), None
        )
        if active_row is None:
            context.session.tenant_id = None
        else:
            _, active_tenant_model, active_role = active_row
            permissions = context.db.scalars(
                select(Permission.code)
                .join(RolePermission, RolePermission.permission_id == Permission.id)
                .where(RolePermission.role_id == active_role.id)
            ).all()
            active_tenant = {
                "id": active_tenant_model.id,
                "name": active_tenant_model.name,
                "role": active_role.name,
                "permissions": sorted(permissions),
            }
    response.headers["X-CSRF-Token"] = raw_csrf
    context.db.commit()
    return {
        "user": {
            "id": context.user.id,
            "email": context.user.email,
            "full_name": context.user.full_name,
            "is_platform_admin": context.user.is_platform_admin,
        },
        "memberships": [
            {"tenant_id": tenant.id, "tenant_name": tenant.name, "role": role.name}
            for _, tenant, role in memberships
        ],
        "active_tenant": active_tenant,
    }


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    context: AuthContext = Depends(require_csrf_session),
    settings: Settings = Depends(get_settings),
) -> Response:
    context.session.revoked_at = datetime.now(UTC)
    context.session.revoked_reason = "logout"
    _audit(context.db, "auth.logout", context.user.id, request)
    context.db.commit()
    _clear_session_cookie(response, settings)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.post("/password/change", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    payload: PasswordChangeInput,
    request: Request,
    response: Response,
    context: AuthContext = Depends(require_csrf_session),
    settings: Settings = Depends(get_settings),
) -> Response:
    try:
        validate_password(payload.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="PASSWORD_POLICY_VIOLATION") from exc
    if not verify_password(payload.current_password, context.user.password_hash):
        raise HTTPException(status_code=400, detail="CURRENT_PASSWORD_INVALID")
    now = datetime.now(UTC)
    context.user.password_hash = hash_password(payload.new_password)
    context.db.execute(
        update(IdentitySession)
        .where(IdentitySession.user_id == context.user.id, IdentitySession.revoked_at.is_(None))
        .values(revoked_at=now, revoked_reason="password_changed")
    )
    _audit(context.db, "auth.password.change", context.user.id, request)
    context.db.commit()
    _clear_session_cookie(response, settings)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/sessions")
def list_sessions(context: AuthContext = Depends(require_session)) -> dict[str, object]:
    sessions = context.db.scalars(
        select(IdentitySession)
        .where(
            IdentitySession.user_id == context.user.id,
            IdentitySession.revoked_at.is_(None),
            IdentitySession.idle_expires_at > datetime.now(UTC),
            IdentitySession.absolute_expires_at > datetime.now(UTC),
        )
        .order_by(IdentitySession.created_at.desc())
    ).all()
    context.db.commit()
    return {
        "data": [
            {
                "id": str(item.id),
                "ip": item.ip,
                "user_agent": item.user_agent,
                "created_at": item.created_at,
                "last_seen_at": item.last_seen_at,
                "idle_expires_at": item.idle_expires_at,
                "absolute_expires_at": item.absolute_expires_at,
                "current": item.id == context.session.id,
            }
            for item in sessions
        ]
    }


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_session(
    session_id: UUID,
    request: Request,
    response: Response,
    context: AuthContext = Depends(require_csrf_session),
    settings: Settings = Depends(get_settings),
) -> Response:
    target = context.db.scalar(
        select(IdentitySession).where(
            IdentitySession.id == session_id, IdentitySession.user_id == context.user.id
        )
    )
    if target is None:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    if target.revoked_at is None:
        target.revoked_at = datetime.now(UTC)
        target.revoked_reason = "user_revoked"
        _audit(context.db, "auth.session.revoked", context.user.id, request)
        context.db.commit()
    if target.id == context.session.id:
        _clear_session_cookie(response, settings)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
