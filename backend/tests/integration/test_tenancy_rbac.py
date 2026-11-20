from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.core.config import reset_settings_cache
from app.core.db import get_engine
from app.main import app
from app.modules.audit.models import AuditLog
from app.modules.identity.models import Session as IdentitySession
from app.modules.identity.models import User
from app.modules.identity.rate_limit import registration_limiter
from app.modules.identity.security import hash_password
from app.modules.tenancy.models import Membership, Role, Tenant
from app.modules.tenancy.service import create_tenant

pytestmark = pytest.mark.integration
ORIGIN = "http://localhost:3000"
PASSWORD = "correct horse battery staple 2026"


def _seed_user(role_name: str = "owner") -> tuple[User, Tenant]:
    with OrmSession(get_engine()) as db:
        user = User(
            email=f"tenancy-{uuid.uuid4().hex}@example.test",
            password_hash=hash_password(PASSWORD),
            full_name="Tenancy Test User",
            is_active=True,
        )
        db.add(user)
        db.flush()
        tenant, _ = create_tenant(db, user, "Tenancy Test Workspace")
        if role_name != "owner":
            role = db.scalar(select(Role).where(Role.name == role_name))
            membership = db.scalar(
                select(Membership).where(
                    Membership.user_id == user.id, Membership.tenant_id == tenant.id
                )
            )
            assert role is not None and membership is not None
            membership.role_id = role.id
        db.commit()
        db.refresh(user)
        db.refresh(tenant)
        return user, tenant


def _login_and_activate(client: TestClient, user: User, tenant: Tenant) -> str:
    login = client.post(
        "/api/v1/auth/login",
        headers={"Origin": ORIGIN},
        json={"email": user.email, "password": PASSWORD},
    )
    assert login.status_code == 200
    csrf = login.headers["x-csrf-token"]
    activated = client.post(
        f"/api/v1/tenants/{tenant.id}/activate",
        headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
    )
    assert activated.status_code == 204
    return csrf


def test_registration_creates_user_tenant_owner_and_session_atomically(monkeypatch) -> None:
    monkeypatch.setenv("ALLOW_REGISTRATION", "true")
    reset_settings_cache()
    registration_limiter.clear()
    email = f"new-{uuid.uuid4().hex}@example.test"
    try:
        with TestClient(app, base_url=ORIGIN) as client:
            response = client.post(
                "/api/v1/auth/register",
                headers={"Origin": ORIGIN},
                json={
                    "email": email,
                    "password": PASSWORD,
                    "full_name": "New Tenant Owner",
                    "tenant_name": "New Workspace",
                    "currency_code": "IRT",
                },
            )
            assert response.status_code == 201, response.text
            assert response.json()["role"] == "owner"
            assert client.cookies.get("mp_session")
            assert response.headers["x-csrf-token"]
            me = client.get("/api/v1/auth/me", headers={"Origin": ORIGIN})
            assert me.status_code == 200
            active_tenant = me.json()["active_tenant"]
            assert active_tenant["role"] == "owner"
            assert "tenant:manage" in active_tenant["permissions"]
            with OrmSession(get_engine()) as db:
                user = db.scalar(select(User).where(User.email == email))
                assert user is not None
                memberships = db.scalars(
                    select(Membership).where(Membership.user_id == user.id)
                ).all()
                assert len(memberships) == 1
                role = db.get(Role, memberships[0].role_id)
                assert role is not None and role.name == "owner"
                sessions = db.scalars(
                    select(IdentitySession).where(IdentitySession.user_id == user.id)
                ).all()
                assert len(sessions) == 1
                assert sessions[0].tenant_id == memberships[0].tenant_id
    finally:
        reset_settings_cache()
        monkeypatch.delenv("ALLOW_REGISTRATION", raising=False)


def test_tenant_switch_is_membership_scoped_and_changes_permissions() -> None:
    user, first_tenant = _seed_user("owner")
    with OrmSession(get_engine()) as db:
        db_user = db.get(User, user.id)
        assert db_user is not None
        second_tenant, _ = create_tenant(db, db_user, "Second Workspace")
        db.commit()
        db.refresh(second_tenant)
    with TestClient(app, base_url=ORIGIN) as client:
        csrf = _login_and_activate(client, user, first_tenant)
        first_me = client.get("/api/v1/auth/me", headers={"Origin": ORIGIN})
        assert first_me.json()["active_tenant"]["id"] == first_tenant.id
        csrf = first_me.headers["x-csrf-token"]
        switched = client.post(
            f"/api/v1/tenants/{second_tenant.id}/activate",
            headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
        )
        assert switched.status_code == 204
        second_me = client.get("/api/v1/auth/me", headers={"Origin": ORIGIN})
        assert second_me.json()["active_tenant"]["id"] == second_tenant.id
        csrf = second_me.headers["x-csrf-token"]
        assert client.get(f"/api/v1/tenants/{first_tenant.id}/members").status_code == 404
        assert client.get(f"/api/v1/tenants/{second_tenant.id}/members").status_code == 200
        _, unrelated_tenant = _seed_user("owner")
        foreign = client.post(
            f"/api/v1/tenants/{unrelated_tenant.id}/activate",
            headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
        )
        assert foreign.status_code == 404


def test_viewer_cannot_manage_members_and_last_owner_is_protected() -> None:
    owner, tenant = _seed_user("owner")
    with TestClient(app, base_url=ORIGIN) as client:
        csrf = _login_and_activate(client, owner, tenant)
        protected = client.delete(
            f"/api/v1/tenants/{tenant.id}/members/{owner.id}",
            headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
        )
        assert protected.status_code == 409
        assert protected.json()["error"]["code"] == "SOLE_OWNER_PROTECTED"
        demoted = client.patch(
            f"/api/v1/tenants/{tenant.id}/members/{owner.id}",
            headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
            json={"role": "admin"},
        )
        assert demoted.status_code == 409
        assert demoted.json()["error"]["code"] == "SOLE_OWNER_PROTECTED"
        with OrmSession(get_engine()) as db:
            membership = db.scalar(
                select(Membership).where(
                    Membership.user_id == owner.id, Membership.tenant_id == tenant.id
                )
            )
            assert membership is not None and membership.status == "active"
            audit = db.scalar(
                select(AuditLog).where(
                    AuditLog.tenant_id == tenant.id,
                    AuditLog.action == "member.owner_protected",
                )
            )
            assert audit is not None

    viewer, viewer_tenant = _seed_user("viewer")
    with TestClient(app, base_url=ORIGIN) as client:
        csrf = _login_and_activate(client, viewer, viewer_tenant)
        allowed_read = client.get(f"/api/v1/tenants/{viewer_tenant.id}/members")
        assert allowed_read.status_code == 200
        denied_write = client.post(
            f"/api/v1/tenants/{viewer_tenant.id}/members",
            headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
            json={"email": "nobody@example.test", "role": "viewer"},
        )
        assert denied_write.status_code == 403


def test_member_lifecycle_and_platform_admin_has_no_tenant_access() -> None:
    owner, tenant = _seed_user("owner")
    new_member, _ = _seed_user("viewer")
    with TestClient(app, base_url=ORIGIN) as client:
        csrf = _login_and_activate(client, owner, tenant)
        headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf}
        added = client.post(
            f"/api/v1/tenants/{tenant.id}/members",
            headers=headers,
            json={"email": new_member.email, "role": "analyst"},
        )
        assert added.status_code == 201, added.text
        assert added.json()["data"]["role"] == "analyst"
        changed = client.patch(
            f"/api/v1/tenants/{tenant.id}/members/{new_member.id}",
            headers=headers,
            json={"role": "viewer"},
        )
        assert changed.status_code == 200
        removed = client.delete(
            f"/api/v1/tenants/{tenant.id}/members/{new_member.id}", headers=headers
        )
        assert removed.status_code == 204
        reactivated = client.post(
            f"/api/v1/tenants/{tenant.id}/members",
            headers=headers,
            json={"email": new_member.email, "role": "viewer"},
        )
        assert reactivated.status_code == 201

    platform_user, platform_tenant = _seed_user("owner")
    with OrmSession(get_engine()) as db:
        persisted = db.get(User, platform_user.id)
        assert persisted is not None
        persisted.is_platform_admin = True
        db.commit()
    with TestClient(app, base_url=ORIGIN) as client:
        login = client.post(
            "/api/v1/auth/login",
            headers={"Origin": ORIGIN},
            json={"email": platform_user.email, "password": PASSWORD},
        )
        assert login.status_code == 200
        headers = {"Origin": ORIGIN, "X-CSRF-Token": login.headers["x-csrf-token"]}
        assert client.get("/api/v1/tenants").status_code == 403
        denied = client.post(f"/api/v1/tenants/{platform_tenant.id}/activate", headers=headers)
        assert denied.status_code == 403


def test_authenticated_user_can_create_and_switch_to_new_tenant() -> None:
    user, first_tenant = _seed_user("owner")
    with TestClient(app, base_url=ORIGIN) as client:
        csrf = _login_and_activate(client, user, first_tenant)
        created = client.post(
            "/api/v1/tenants",
            headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
            json={"name": "Another Workspace", "currency_code": "IRR"},
        )
        assert created.status_code == 201, created.text
        new_tenant = created.json()["data"]
        assert new_tenant["role"] == "owner"
        me = client.get("/api/v1/auth/me", headers={"Origin": ORIGIN})
        assert me.json()["active_tenant"]["id"] == new_tenant["id"]
        tenants = client.get("/api/v1/tenants")
        assert tenants.status_code == 200
        assert len(tenants.json()["data"]) == 2


def test_registration_is_closed_by_default() -> None:
    email = f"closed-{uuid.uuid4().hex}@example.test"
    with TestClient(app, base_url=ORIGIN) as client:
        response = client.post(
            "/api/v1/auth/register",
            headers={"Origin": ORIGIN},
            json={
                "email": email,
                "password": PASSWORD,
                "full_name": "Closed Registration",
                "tenant_name": "Should Not Exist",
            },
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "REGISTRATION_CLOSED"
    with OrmSession(get_engine()) as db:
        assert db.scalar(select(User.id).where(User.email == email)) is None


def test_suspended_tenant_cannot_be_activated_or_used() -> None:
    user, tenant = _seed_user("owner")
    with OrmSession(get_engine()) as db:
        persisted = db.get(Tenant, tenant.id)
        assert persisted is not None
        persisted.status = "suspended"
        db.commit()
    with TestClient(app, base_url=ORIGIN) as client:
        login = client.post(
            "/api/v1/auth/login",
            headers={"Origin": ORIGIN},
            json={"email": user.email, "password": PASSWORD},
        )
        assert login.status_code == 200
        headers = {"Origin": ORIGIN, "X-CSRF-Token": login.headers["x-csrf-token"]}
        activation = client.post(f"/api/v1/tenants/{tenant.id}/activate", headers=headers)
        assert activation.status_code == 403
        assert activation.json()["error"]["code"] == "TENANT_SUSPENDED"
        with OrmSession(get_engine()) as db:
            session = db.scalar(select(IdentitySession).where(IdentitySession.user_id == user.id))
            assert session is not None
            session.tenant_id = tenant.id
            db.commit()
        denied = client.get(f"/api/v1/tenants/{tenant.id}/members")
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "TENANT_SUSPENDED"
