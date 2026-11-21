# Phase 7 — MVP UI, Dashboard & Reports

**Branch:** `phase7-mvp-ui`  
**Base:** Phase 6 CI-green commit `2cf453a0ad0ee523da43ba6a891bd2c31cf4de83`  
**Status:** Plan — implementation not yet started  
**Product constraint:** Deliver the smallest complete user-facing workflow for the first Iranian small-business customers. No redesign of the backend domains and no feature expansion beyond the approved MVP.

## 1. Goal and delivery rule

A tenant user must be able to use MarginPilot without calling the API manually:

1. Sign in and work inside the correct business (tenant).
2. Manage products and suppliers, import catalog/price data, and resolve supplier-price comparisons.
3. Record sales, returns (where permitted by the backend state rules), and expenses.
4. See reliable product and business profitability using the Phase 6 API as the only financial source.
5. Export the supported reports.

The UI must never calculate profit, allocate discounts/expenses, or derive a suggested price independently. It displays backend results and their warnings, currency, formula version, and data-through timestamp.

## 2. Evidence-based starting point

- The current frontend is a Vite/React/TypeScript shell with one WelcomePage and a backend readiness probe; there is no authenticated application shell or business workflow UI yet.
- React Router 7, TanStack Query 5, Tailwind 4, and Vazirmatn are already installed.
- Backend APIs for identity/tenancy, catalog, suppliers, imports, comparison, sales/returns/refunds, expenses, pricing suggestions, and analytics are available on `phase6-financial-engine`.
- Phase 6 analytics endpoints are `GET /api/v1/analytics/summary`, `/products`, `/trends`, and `/expenses`. They require `analytics:read`; order profit and price suggestion require `pricing:read`.
- The current repository does not yet contain a user-facing reports/export workflow. Export endpoints and their tests are therefore an explicit Phase 7 backend deliverable, not something the browser should fabricate.

## 3. Implementation order (vertical slices)

### 7.1 Application foundation and authentication

- Replace the welcome-only route with a protected application shell, login, logout, session restoration, and a clear unauthenticated state.
- Restore the current user, active tenant, memberships, and permissions from the existing identity API; support tenant activation and refresh the relevant query cache after switching.
- Use the existing opaque HttpOnly session cookie. Send credentials with same-origin requests and retain the CSRF token returned by the API in memory; attach `X-CSRF-Token` to unsafe requests. Never store session tokens in localStorage/sessionStorage.
- Centralize API errors, 401 handling, loading/empty/error states, request cancellation, and query invalidation.
- Render navigation/actions from permissions, while relying on backend authorization as the security boundary.

**Acceptance:** login/session restoration/logout, CSRF-protected mutation, tenant switching, and unauthorized/expired-session behavior have component and API integration coverage.

### 7.2 Catalog, suppliers, imports, and comparison

- Product/category and supplier list/detail/create/edit flows with essential search, filters, and pagination.
- Import flow: upload, inspect detected columns, map fields, preview validation errors/duplicates, then explicit confirmation. Never auto-confirm.
- Supplier price comparison flow: show confirmed matches separately from ambiguous/unmatched rows; require explicit user action to confirm or reject ambiguous matches.
- Surface currency/unit mismatches and source/date context; do not rank incomparable prices as if they were equivalent.

**Acceptance:** a user can create or import catalog/supplier data, preview and confirm an import, and complete a comparison decision without API tooling. Tenant boundaries and permissions are covered by backend integration tests; UI tests verify the user-visible states.

### 7.3 Sales and expenses

- Sales order list/detail/create/edit within backend-allowed states; show immutable item/cost snapshots and payment/shipping status.
- Support physical returns only when the backend allows them; show actual refund amounts and return history. Independent refunds remain limited to eligible cancelled-before-shipment orders.
- Expense list/create/edit/soft-delete with the backend's order/product/period scopes and allocation strategy options.
- Keep forms deliberately small. Use server validation as authoritative and show field-level errors.

**Acceptance:** the user can record a sale and relevant expenses, inspect order details, and perform only valid return/refund actions. No client-side state transition or refund ceiling is trusted.

### 7.4 Dashboard and product analytics

- Dashboard filters: date range; display tenant currency and `data_through`.
- Summary KPIs: revenue, gross/net profit, margin, sales count, units, returns/refunds, and expense totals, exactly as returned by the analytics API.
- Product profitability table with profitable/unprofitable/unknown-cost states and product detail drill-down.
- Daily/monthly trend chart using the analytics trends endpoint.
- Warnings (unknown cost, unallocated expenses, cancelled-order costs) must be visible and explained; never present unknown profit as zero.
- Do not add custom metrics or client-side aggregation unless their definition is documented and independently tested.

**Acceptance:** displayed totals reconcile exactly with API payloads; unknown values and warnings remain explicit; date range and currency are visible.

### 7.5 Report exports

- Add tenant-scoped backend export endpoints for the MVP reports (summary, product profitability, supplier comparison) in XLSX and PDF only where the output is useful and supported.
- Reuse the same service-level query/calculation outputs as analytics; do not duplicate FV-2 formulas in export code.
- Protect every export with the relevant read permission and tenant scope.
- Stream files with correct MIME type and safe filenames. Prevent spreadsheet formula injection in all user-controlled text cells; test Persian text/RTL and numeric formatting.
- If an export type is not ready, do not show a non-functional download control.

**Acceptance:** export contents reconcile with the corresponding API response; cross-tenant access is denied; XLSX/PDF open correctly and Persian text is preserved.

## 4. Frontend structure and technology decisions

- Keep one Vite application and one deployable frontend; no micro-frontends.
- Feature folders: `auth`, `tenants`, `catalog`, `suppliers`, `imports`, `comparison`, `sales`, `expenses`, `analytics`, and `reports`.
- Shared layers: typed API client, auth/tenant context, permission helpers, query keys, reusable table/form/feedback components, and a small RTL design system.
- Keep TanStack Query as the server-state cache. Do not mirror server entities in a second global state store.
- Use React Hook Form + Zod for non-trivial forms. Add ECharts only for the dashboard trend chart. Avoid a large component framework and avoid dependencies without a concrete Phase 7 use.
- Persian (fa-IR) and RTL are defaults; format dates and numbers with locale-aware browser formatters while preserving raw API values for calculations/display.
- All financial values are rendered from decimal strings; do not coerce them to JavaScript Number for arithmetic.

## 5. Explicitly out of scope

- Custom report builder, configurable dashboards, drag-and-drop widgets.
- Client-side financial calculations or editable formula definitions.
- Accounting/ledger, inventory management, payment gateway, AI insights, mobile app, multi-region, and microservices.
- Real-time websockets, offline mode, complex global state, and premature performance optimization.
- Bulk workflows not required by the first end-to-end customer journey.

## 6. Quality gates

- TypeScript strict build and ESLint.
- Component tests for authentication, forms, permissions, table states, warnings, and RTL.
- Playwright E2E for the critical journey: sign in → select tenant → import/catalog → supplier comparison → record sale/expense → view profit → export report.
- Backend tests for every new export endpoint: real PostgreSQL, tenant isolation, permission enforcement, output validity, spreadsheet formula injection, and Persian content.
- Accessibility basics: semantic controls, keyboard operation, visible focus, labels, and status announcements.
- CI green (frontend lint/type-check/Vitest/build, backend Ruff/mypy/unit/PostgreSQL integration, Docker build, dependency and secret scans).
- No merge to `main`, PR, or release without separate explicit authorization.

## 7. Phase completion criteria

Phase 7 is complete only when the critical customer journey works end-to-end through the UI, all visible financial figures match the Phase 6 API, exports are validated, E2E tests pass, documentation is aligned, and the full CI gate is green. Phase 8 then performs release-readiness, backup/restore, security, and deployment verification.
