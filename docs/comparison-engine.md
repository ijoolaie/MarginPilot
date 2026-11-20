# Supplier Price Comparison - Phase 4 Step 4

## Purpose

Compare two immutable, finalized supplier price lists in one active tenant. A run is a snapshot: later price-list edits are not possible because final lists are immutable, and a later comparison creates a new run.

## API

All endpoints are under `/api/v1/comparison`.

- `POST /runs` - requires `comparison:write`, a mandatory `Idempotency-Key`, and `{base_list_id, target_list_id, match_strategy}`. The two list IDs must differ, both lists must be final and tenant-owned, and every price row must use the tenant currency.
- `GET /runs` - requires `comparison:read`; paginated history.
- `GET /runs/{id}` - requires `comparison:read`; paginated match details and optional status filter. It returns both list titles/supplier names and each side's SKU, raw name, price, unit and currency.
- `POST /runs/{id}/confirm-matches` - requires `comparison:write`; accepts up to 500 decisions per request. A decision is `{match_id, decision: confirm|reject, product_id?, peer_price_id?}`.

## Matching rules

- `sku`: case-folded, trimmed exact SKU only.
- `normalized_name`: exact normalized name only.
- `sku_then_name`: exact SKU first, then exact normalized name for remaining rows.
- Name normalization applies Unicode NFKC, Persian/Arabic Yeh and Kaf normalization, removes zero-width joiners and directional marks, ignores punctuation differences and collapses whitespace. It is deterministic and is not fuzzy matching.
- A one-to-one key match is paired. If a normalized key is duplicated on either side, all rows in that ambiguous group remain separate uncertain candidates; no arbitrary row ordering is used to pair them.
- One-sided non-ambiguous rows are classified as new (target only) or removed (base only).

## Price arithmetic

`price_delta = target.unit_price - base.unit_price`. Positive means increased; negative means decreased; zero means unchanged. Percentage is `(delta / base_price) * 100`, rounded to four decimal places using `ROUND_HALF_UP`. The percentage column is `NUMERIC(26,4)` so it can store the full range implied by `supplier_prices.unit_price NUMERIC(20,2)`. All non-primary-key foreign-key columns have supporting indexes, including optional references. When the base price is zero, percentage is `null` to avoid division by zero. If either unit is null or units differ, no delta or percentage is calculated and the match remains uncertain.

Currency conversion and unit conversion are intentionally unsupported. The run rejects rows whose currency differs from the tenant currency.

## Manual review and product linking

- Uncertain one-sided candidates can be paired explicitly by supplying `peer_price_id` from the opposite list. This is an explicit user choice, not an automatic suggestion.
- Confirmation requires an active tenant product. Both price rows must have the exact same unit as the product.
- Existing product links must be empty or already point to the selected product. Conflicting links are rejected.
- The selected product is written to both supplier-price rows; the comparison row stores `confirmed_product_id`, delta and percentage. The counterpart one-sided candidate row is removed. All changes, run summary/status and audit event commit atomically.
- Rejecting a one-sided candidate changes only its review state; supplier-price rows are not modified. Rejecting a two-sided non-comparable/uncertain pair splits it into separate confirmed new/removed lines, without changing supplier-price rows. The review action is recorded in the audit log.
- Replaying an identical confirmation is safe. Conflicting transitions return 409.

## Persistence and bounds

`comparison_runs` and `comparison_matches` use tenant-aware composite FKs. `base_price_id` and `target_price_id` are nullable so additions and removals can be represented; at least one side is required. Partial unique indexes prevent a price row from appearing twice on the same side of a run. Summary counters are recomputed after manual review; price-trend counters include confirmed pairs only, while unresolved candidate deltas remain visible in match details but are excluded from aggregate increase/decrease totals. Supporting indexes cover every non-primary-key foreign-key lookup.

`COMPARISON_MAX_ROWS_PER_LIST` defaults to 100,000. Comparisons run synchronously within that bound. Background jobs are deferred until production volume justifies them.

## Deliberate exclusions

No fuzzy/AI matching, currency conversion, unit conversion, sales-order comparisons, background worker or frontend UI is included in this step.

## Verification results

### Local verification

- PostgreSQL migration chain: full downgrade to `base`, upgrade to revision `d4f5a6b7c8d9`, and `alembic check` all passed.
- Comparison integration tests: 6 passed, covering idempotency, tenant isolation, RBAC, atomic rollback on unit mismatch, manual peer pairing, rejection/splitting, and schema/FK/index inspection.
- Full backend suite: 114 passed (70 unit + 44 PostgreSQL integration tests).
- Ruff and strict mypy (42 source files) passed; `pip check` reported no broken requirements; hash-locked `pip-audit` reported no known vulnerabilities.
- Local Docker image build was not run because the exact pinned Python base-image digest was not cached. No substitute digest or pull was used.

### GitHub Actions verification

- Workflow run [44696157933](https://github.com/ijoolaie/MarginPilot/actions/runs/44696157933) completed successfully: 4/4 jobs passed.
- CI covered backend tests, frontend checks, Docker backend/frontend image builds, dependency security audit, and Gitleaks secret scanning.
