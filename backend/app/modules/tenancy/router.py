"""Tenant lifecycle, tenant selection, and membership administration API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session as OrmSession

from app.core.config import Settings, get_settings
from app.modules.audit.models import AuditLog
from app.modules.identity.models import User
from app.modules.identity.router import AuthContext, require_csrf_session, require_session
from app.modules.tenancy.dependencies import TenantContext, require_permission
from app.modules.tenancy.models import Membership, Role, Tenant
from app.modules.tenancy.service import create_tenant

router = APIRouter(prefix="/tenants", tags=["tenants"])


class TenantCreateInput(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    currency_code: str = Field(default="IRT", pattern=r"^(IRT|IRR)$")

    @field_validator("name")
    @classmethod
    def strip_nonempty_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Tenant name cannot be blank.")
        return normalized


class TenantUpdateInput(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    currency_code: str | None = Field(default=None, pattern=r"^(IRT|IRR)$")


class MemberCreateInput(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    role: str = Field(pattern=r"^(admin|analyst|viewer)$")

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


class MemberUpdateInput(BaseModel):
    role: str | None = Field(default=None, pattern=r"^(admin|analyst|viewer)$")
    status: str | None = Field(default=None, pattern=r"^(active|revoked)$")


def _audit(
    db: OrmSession,
    request: Request,
    user_id: int,
    tenant_id: int,
    action: str,
    entity_type: str,
    entity_id: str,
    detail: dict[str, object] | None = None,
) -> None:
    db.add(
        AuditLog(
            user_id=user_id,
            tenant_id=tenant_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            detail=detail or {},
            ip=request.client.host if request.client else None,
        )
    )


def _assert_path_tenant(tenant_id: int, context: TenantContext) -> None:
    if tenant_id != context.tenant.id:
        raise HTTPException(status_code=404, detail="NOT_FOUND")


@router.get("")
def list_tenants(auth: AuthContext = Depends(require_session)) -> dict[str, object]:
    if auth.user.is_platform_admin:
        raise HTTPException(status_code=403, detail="PERMISSION_DENIED")
    rows = auth.db.execute(
        select(Tenant, Role, Membership)
        .join(Membership, Membership.tenant_id == Tenant.id)
        .join(Role, Role.id == Membership.role_id)
        .where(
            Membership.user_id == auth.user.id,
            Membership.status == "active",
            Tenant.status == "active",
            Tenant.deleted_at.is_(None),
        )
        .order_by(Tenant.id)
    ).all()
    auth.db.commit()
    return {
        "data": [
            {
                "id": tenant.id,
                "name": tenant.name,
                "slug": tenant.slug,
                "currency_code": tenant.currency_code,
                "role": role.name,
                "active": auth.session.tenant_id == tenant.id,
            }
            for tenant, role, _ in rows
        ]
    }


@router.post("", status_code=status.HTTP_201_CREATED)
def create_tenant_endpoint(
    payload: TenantCreateInput,
    request: Request,
    auth: AuthContext = Depends(require_csrf_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    if auth.user.is_platform_admin:
        raise HTTPException(status_code=403, detail="PERMISSION_DENIED")
    tenant, membership = create_tenant(
        auth.db, auth.user, payload.name, payload.currency_code, settings.max_tenants_per_user
    )
    auth.session.tenant_id = tenant.id
    _audit(
        auth.db,
        request,
        auth.user.id,
        tenant.id,
        "tenant.created",
        "tenant",
        str(tenant.id),
        {"membership_id": membership.id},
    )
    auth.db.commit()
    return {
        "data": {
            "id": tenant.id,
            "name": tenant.name,
            "slug": tenant.slug,
            "currency_code": tenant.currency_code,
            "role": "owner",
        }
    }


@router.post("/{tenant_id}/activate")
def activate_tenant(
    tenant_id: int,
    request: Request,
    auth: AuthContext = Depends(require_csrf_session),
) -> Response:
    if auth.user.is_platform_admin:
        raise HTTPException(status_code=403, detail="PERMISSION_DENIED")
    row = auth.db.execute(
        select(Membership, Tenant)
        .join(Tenant, Tenant.id == Membership.tenant_id)
        .where(
            Membership.user_id == auth.user.id,
            Membership.tenant_id == tenant_id,
            Membership.status == "active",
            Tenant.deleted_at.is_(None),
        )
        .with_for_update()
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    _, tenant = row
    if tenant.status != "active":
        raise HTTPException(status_code=403, detail="TENANT_SUSPENDED")
    auth.session.tenant_id = tenant.id
    _audit(auth.db, request, auth.user.id, tenant.id, "tenant.switched", "tenant", str(tenant.id))
    auth.db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/{tenant_id}")
def update_tenant(
    tenant_id: int,
    payload: TenantUpdateInput,
    request: Request,
    auth: AuthContext = Depends(require_csrf_session),
    context: TenantContext = Depends(require_permission("tenant:manage")),
) -> dict[str, object]:
    _assert_path_tenant(tenant_id, context)
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="REQUEST_INVALID")
    if "name" in changes and changes["name"] is not None:
        context.tenant.name = str(changes["name"]).strip()
    if "currency_code" in changes and changes["currency_code"] is not None:
        context.tenant.currency_code = str(changes["currency_code"])
    _audit(
        auth.db,
        request,
        auth.user.id,
        tenant_id,
        "tenant.updated",
        "tenant",
        str(tenant_id),
        changes,
    )
    auth.db.commit()
    return {
        "data": {
            "id": tenant_id,
            "name": context.tenant.name,
            "currency_code": context.tenant.currency_code,
        }
    }


@router.get("/{tenant_id}/members")
def list_members(
    tenant_id: int,
    context: TenantContext = Depends(require_permission("member:read")),
) -> dict[str, object]:
    _assert_path_tenant(tenant_id, context)
    rows = context.auth.db.execute(
        select(User, Role, Membership)
        .join(Membership, Membership.user_id == User.id)
        .join(Role, Role.id == Membership.role_id)
        .where(
            Membership.tenant_id == tenant_id,
            Membership.status != "revoked",
            User.is_active.is_(True),
        )
        .order_by(User.id)
    ).all()
    context.auth.db.commit()
    return {
        "data": [
            {
                "user_id": user.id,
                "email": user.email,
                "full_name": user.full_name,
                "role": role.name,
                "status": membership.status,
                "created_at": membership.created_at,
            }
            for user, role, membership in rows
        ]
    }


@router.post("/{tenant_id}/members", status_code=status.HTTP_201_CREATED)
def add_member(
    tenant_id: int,
    payload: MemberCreateInput,
    request: Request,
    auth: AuthContext = Depends(require_csrf_session),
    context: TenantContext = Depends(require_permission("member:manage")),
) -> dict[str, object]:
    _assert_path_tenant(tenant_id, context)
    tenant = auth.db.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
    if tenant is None or tenant.status != "active" or tenant.deleted_at is not None:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    email = payload.email.strip().casefold()
    target_user = auth.db.scalar(select(User).where(User.email == email).with_for_update())
    if target_user is None or not target_user.is_active or target_user.is_platform_admin:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    role = auth.db.scalar(select(Role).where(Role.name == payload.role))
    if role is None:
        raise RuntimeError("Requested system role is missing")
    membership = auth.db.scalar(
        select(Membership)
        .where(Membership.user_id == target_user.id, Membership.tenant_id == tenant_id)
        .with_for_update()
    )
    if membership is None:
        membership = Membership(
            user_id=target_user.id,
            tenant_id=tenant_id,
            role_id=role.id,
            status="active",
        )
        auth.db.add(membership)
    elif membership.status == "active":
        raise HTTPException(status_code=409, detail="MEMBERSHIP_ALREADY_ACTIVE")
    else:
        membership.role_id = role.id
        membership.status = "active"
    _audit(
        auth.db,
        request,
        auth.user.id,
        tenant_id,
        "member.added",
        "user",
        str(target_user.id),
        {"role": payload.role},
    )
    auth.db.commit()
    return {
        "data": {
            "user_id": target_user.id,
            "email": target_user.email,
            "role": role.name,
            "status": "active",
        }
    }


@router.patch("/{tenant_id}/members/{user_id}")
def update_member(
    tenant_id: int,
    user_id: int,
    payload: MemberUpdateInput,
    request: Request,
    auth: AuthContext = Depends(require_csrf_session),
    context: TenantContext = Depends(require_permission("member:manage")),
) -> dict[str, object]:
    _assert_path_tenant(tenant_id, context)
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="REQUEST_INVALID")
    tenant = auth.db.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
    if tenant is None:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    row = auth.db.execute(
        select(Membership, Role)
        .join(Role, Role.id == Membership.role_id)
        .where(Membership.tenant_id == tenant_id, Membership.user_id == user_id)
        .with_for_update()
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    membership, current_role = row
    if current_role.name == "owner" and ("role" in changes or changes.get("status") == "revoked"):
        owner_count = (
            auth.db.scalar(
                select(func.count(Membership.id))
                .join(Role, Role.id == Membership.role_id)
                .where(
                    Membership.tenant_id == tenant_id,
                    Membership.status == "active",
                    Role.name == "owner",
                )
            )
            or 0
        )
        if owner_count <= 1:
            _audit(
                auth.db,
                request,
                auth.user.id,
                tenant_id,
                "member.owner_protected",
                "user",
                str(user_id),
            )
            auth.db.commit()
            raise HTTPException(status_code=409, detail="SOLE_OWNER_PROTECTED")
    if "role" in changes:
        new_role = auth.db.scalar(select(Role).where(Role.name == changes["role"]))
        if new_role is None:
            raise HTTPException(status_code=422, detail="REQUEST_INVALID")
        membership.role_id = new_role.id
    if "status" in changes:
        membership.status = str(changes["status"])
    _audit(
        auth.db,
        request,
        auth.user.id,
        tenant_id,
        "member.role_changed" if "role" in changes else "member.status_changed",
        "user",
        str(user_id),
        changes,
    )
    auth.db.commit()
    return {
        "data": {
            "user_id": user_id,
            "role": changes.get("role", current_role.name),
            "status": membership.status,
        }
    }


@router.delete("/{tenant_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    tenant_id: int,
    user_id: int,
    request: Request,
    auth: AuthContext = Depends(require_csrf_session),
    context: TenantContext = Depends(require_permission("member:manage")),
) -> Response:
    _assert_path_tenant(tenant_id, context)
    locked_tenant = auth.db.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
    if locked_tenant is None:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    row = auth.db.execute(
        select(Membership, Role)
        .join(Role, Role.id == Membership.role_id)
        .where(Membership.tenant_id == tenant_id, Membership.user_id == user_id)
        .with_for_update()
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    membership, role = row
    if membership.status == "active" and role.name == "owner":
        owner_count = (
            auth.db.scalar(
                select(func.count(Membership.id))
                .join(Role, Role.id == Membership.role_id)
                .where(
                    Membership.tenant_id == tenant_id,
                    Membership.status == "active",
                    Role.name == "owner",
                )
            )
            or 0
        )
        if owner_count <= 1:
            _audit(
                auth.db,
                request,
                auth.user.id,
                tenant_id,
                "member.owner_protected",
                "user",
                str(user_id),
            )
            auth.db.commit()
            raise HTTPException(status_code=409, detail="SOLE_OWNER_PROTECTED")
    membership.status = "revoked"
    _audit(auth.db, request, auth.user.id, tenant_id, "member.removed", "user", str(user_id))
    auth.db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
