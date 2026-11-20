"""Tenant lifecycle and membership service operations."""

from __future__ import annotations

import re
import unicodedata
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session as OrmSession

from app.modules.identity.models import User
from app.modules.tenancy.models import Membership, Role, Tenant

_RESERVED_SLUGS = frozenset(
    {"api", "admin", "www", "mail", "app", "auth", "static", "assets", "support", "help"}
)


def tenant_slug(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    base = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")[:60].strip("-")
    if not base or base in _RESERVED_SLUGS:
        base = "tenant"
    return f"{base}-{uuid4().hex[:12]}"


def create_tenant(
    db: OrmSession,
    user: User,
    name: str,
    currency_code: str = "IRT",
    max_tenants_per_user: int = 5,
) -> tuple[Tenant, Membership]:
    """Create tenant and its initial active Owner membership in the caller's transaction."""
    if user.is_platform_admin:
        raise HTTPException(status_code=403, detail="PERMISSION_DENIED")
    locked_user = db.scalar(select(User).where(User.id == user.id).with_for_update())
    if locked_user is None or not locked_user.is_active:
        raise HTTPException(status_code=401, detail="AUTH_REQUIRED")
    current_count = (
        db.scalar(
            select(func.count(Membership.id))
            .join(Tenant, Tenant.id == Membership.tenant_id)
            .where(
                Membership.user_id == user.id,
                Membership.status == "active",
                Tenant.status == "active",
                Tenant.deleted_at.is_(None),
            )
        )
        or 0
    )
    if current_count >= max_tenants_per_user:
        raise HTTPException(status_code=409, detail="MAX_TENANTS_PER_USER_REACHED")
    owner_role = db.scalar(select(Role).where(Role.name == "owner"))
    if owner_role is None:
        raise RuntimeError("System role seed is missing: owner")
    tenant = Tenant(
        name=name.strip(),
        slug=tenant_slug(name),
        currency_code=currency_code,
        status="active",
    )
    db.add(tenant)
    db.flush()
    membership = Membership(
        user_id=user.id,
        tenant_id=tenant.id,
        role_id=owner_role.id,
        status="active",
    )
    db.add(membership)
    db.flush()
    return tenant, membership
