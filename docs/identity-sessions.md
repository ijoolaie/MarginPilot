# Phase 3 — Identity and Session Security

## Delivered in Step 2

- Password hashing and verification use `argon2-cffi==25.1.0` with Argon2id (`time_cost=3`, `memory_cost=65536 KiB`, `parallelism=4`). Passwords are accepted from 12 through 128 characters.
- `POST /api/v1/auth/login` validates `Origin`/`Referer` against `CORS_ORIGINS`, applies the per-IP-and-normalized-email login window, performs a dummy Argon2 verification for unknown/inactive accounts, persists failed-attempt lockout state, and creates a new opaque session on success.
- Session and CSRF values each use 32 bytes of CSPRNG entropy. Only SHA-256 digests are persisted. The session value is delivered only in the `mp_session` HttpOnly cookie; the CSRF value is delivered in the `X-CSRF-Token` response header.
- `GET /api/v1/auth/me` rotates the session-bound CSRF token and returns the current user and active memberships. Because this GET mutates CSRF state, it also requires an allowlisted Origin/Referer. `X-CSRF-Token` is exposed by CORS for the SPA. Tenant permissions are added with Step 3 RBAC.
- Logout, password change, and session revocation require both an allowlisted Origin/Referer and the session-bound CSRF header. Password change revokes every active session for that user.
- Idle and absolute session deadlines are refreshed/bounded using the configured values (7 days idle, 30 days absolute in `.env.example`). Cookies use HttpOnly, Secure by default, SameSite=Lax, and Path=/.
- Login success/failure, logout, password change, and session revocation produce audit events without recording credentials or raw tokens.
- Internal password-reset token creation/consume primitives persist only the token digest and enforce one-time, expiry-bound use.

## Boundaries carried forward

- Registration is implemented in Step 3 as an atomic user + tenant + initial Owner membership + session transaction. It remains disabled by default (`ALLOW_REGISTRATION=false`) and is rate-limited when enabled.
- Password-reset HTTP endpoints and delivery remain disabled. There is no verified email/SMS delivery channel yet, so a reset token must never be returned through the API or written to logs.
- Tenant switching and permission enforcement are documented in `tenancy-rbac.md`.

## Operational constraints

The login limiter is process-local, bounded, and thread-safe, matching ADR-010. It is appropriate only for the current single-instance deployment. Before running multiple backend replicas, replace it with a shared atomic limiter (for example Redis) so limits cannot be bypassed across workers. Do not trust arbitrary `X-Forwarded-For` values; client-IP extraction must be configured against an explicit trusted-proxy boundary before deployment behind additional proxies.

## Validation

Unit tests cover Argon2id verification, password policy, CSPRNG token hashing, rate-limit windows, and Origin/Referer allowlisting. PostgreSQL integration tests cover login/session creation, digest-only persistence, CSRF enforcement, logout invalidation, password-change revocation, account lockout, idle expiry, and single-use reset tokens.
