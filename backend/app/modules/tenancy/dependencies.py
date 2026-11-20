"""Tenant context and backend-enforced RBAC dependencies."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Depends, HTTPException
from sqlalchemy import select

from app.modules.identity.router import AuthContext, require_session
from app.modules.tenancy.models import Membership, Permission, Role, RolePermission, Tenant


@dataclass(frozen=True)
class TenantContext:
    auth: AuthContext
    tenant: Tenant
    membership: Membership
    role: Role
    permissions: frozenset[str]


def require_tenant_context(
    auth: AuthContext = Depends(require_session),
) -> TenantContext:
    if auth.user.is_platform_admin:
        raise HTTPException(status_code=403, detail="PERMISSION_DENIED")
    tenant_id = auth.session.tenant_id
    if tenant_id is None:
        raise HTTPException(status_code=403, detail="TENANT_CONTEXT_REQUIRED")
    row = auth.db.execute(
        select(Membership, Tenant, Role)
        .join(Tenant, Tenant.id == Membership.tenant_id)
        .join(Role, Role.id == Membership.role_id)
        .where(
            Membership.user_id == auth.user.id,
            Membership.tenant_id == tenant_id,
            Membership.status == "active",
            Tenant.deleted_at.is_(None),
        )
    ).first()
    if row is None:
        # A stale session tenant is cleared; never fall back to platform-admin access.
        auth.session.tenant_id = None
        auth.db.commit()
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    membership, tenant, role = row
    if tenant.status != "active":
        auth.session.tenant_id = None
        auth.db.commit()
        raise HTTPException(status_code=403, detail="TENANT_SUSPENDED")
    permission_codes = frozenset(
        auth.db.scalars(
            select(Permission.code)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .where(RolePermission.role_id == role.id)
        ).all()
    )
    return TenantContext(
        auth=auth,
        tenant=tenant,
        membership=membership,
        role=role,
        permissions=permission_codes,
    )


def require_permission(code: str) -> Callable[..., TenantContext]:
    """Create a dependency that requires both an active tenant and one exact grant."""

    def dependency(context: TenantContext = Depends(require_tenant_context)) -> TenantContext:
        if code not in context.permissions:
            raise HTTPException(status_code=403, detail="PERMISSION_DENIED")
        return context

    return dependency
