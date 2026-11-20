# Phase 3 — Tenancy and RBAC

## Runtime contract

- `POST /api/v1/auth/register` creates a user, one tenant, its initial active `owner` membership, an opaque session, and audit records in one PostgreSQL transaction. The response sets the HttpOnly session cookie and returns the CSRF token in `X-CSRF-Token`. No credential or raw token is written to audit data.
- Public registration is disabled by default (`ALLOW_REGISTRATION=false`). When deliberately enabled, requests are limited per client IP by `RATE_LIMIT_REGISTER_PER_HOUR`; a user may have at most `MAX_TENANTS_PER_USER` active tenant memberships. Both limits are validated settings. The registration limiter is process-local and must be replaced with a shared atomic limiter before multi-replica deployment.
- Tenant slugs are generated from an ASCII-normalized name with a random suffix; reserved base names are avoided. Persian names without an ASCII transliteration receive a safe generated `tenant-<suffix>` slug.
- `POST /api/v1/tenants` creates another tenant and an Owner membership atomically, subject to the same per-user cap, and switches the current session to it. `GET /api/v1/tenants` lists only the caller's active memberships. `POST /api/v1/tenants/{id}/activate` switches only to an active tenant for which the caller has an active membership.
- The active tenant is stored on the server-side session. Every tenant-scoped request resolves and revalidates the session's active membership and tenant status. A stale or foreign tenant context never falls back to another tenant.
- `require_permission(code)` resolves grants from `role_permissions` and `permissions` on the backend. Frontend visibility is not an authorization boundary. `platform_admin` accounts are explicitly denied tenant-context, tenant listing/creation, and tenant switching; the system role has no tenant-level grants and cannot be assigned through member APIs.
- Tenant path IDs must match the active `TenantContext`; mismatches return `404 NOT_FOUND` to avoid confirming another tenant's resources.

## Membership administration

- `GET /tenants/{id}/members` requires `member:read`.
- `POST /tenants/{id}/members` requires `member:manage` and adds an already registered, active user as `admin`, `analyst`, or `viewer`. It can reactivate a revoked membership. Email invitations and outbound delivery are not implemented.
- `PATCH /tenants/{id}/members/{user_id}` can change an existing member's role among those non-owner roles or set membership status to `active`/`revoked`.
- `DELETE /tenants/{id}/members/{user_id}` revokes membership; it does not delete the user or tenant.
- Owner transfer is intentionally outside v1. The API cannot grant the Owner role. Demoting, revoking, or removing the last active Owner is rejected with `409 SOLE_OWNER_PROTECTED` and an audit event. Mutations lock the tenant row before checking active Owner count, serializing concurrent Owner-removal attempts.
- Membership and tenant changes emit audit events. Passwords, session tokens, and CSRF tokens are never included.

## Deliberate boundaries

- The Phase 3 initial migration contains the 11 global identity/tenancy/audit/idempotency tables. Step 3 requires no schema migration.
- `tenant_settings` is not created automatically during tenant registration. Its required `default_allocation_strategy`, `currency_display`, and `round_display_decimals` fields have no approved defaults in the data model. The application does not invent those business defaults; the settings workflow must collect/define them before any feature requires a settings row.
- Domain tables and tenant-aware composite foreign keys are introduced with their corresponding domain modules, not prematurely in this identity/tenancy step. Tenant-scoped service code must receive `TenantContext` and must filter every domain query by its tenant ID.
- Password-reset HTTP delivery remains disabled until a verified delivery channel exists. Email invitation delivery is also not part of this step.

## Validation

PostgreSQL integration coverage includes atomic registration, registration closed by default, tenant creation and switching, cross-tenant 404 behavior, role grant enforcement, member add/update/revoke/reactivation, platform-admin isolation, and last-Owner protection. Unit tests and migration/schema checks run separately. The rate limiter's single-process limitation is an explicit deployment gate.
