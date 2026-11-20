# Import Pipeline — Phase 4 Step 3

## Scope

The v1 import pipeline supports `products` and `supplier_prices` CSV/XLSX files. The schema reserves `sales` as a future kind, but sales imports return `422 IMPORT_KIND_NOT_READY` until the sales domain tables and validation rules are implemented.

The pipeline is deliberately two-phase: upload and parse, then map and validate, then an explicit idempotent confirmation. It never writes catalog or supplier-price domain rows before confirmation.

## API

All endpoints are mounted below `/api/v1` and require the active tenant context.

- `POST /imports` — multipart upload. Fields: `kind`, `file`; for supplier prices also `supplier_id`, optional `price_list_title`, required `received_at`; for XLSX optionally `sheet_name`.
- `GET /imports` and `GET /imports/{id}` — list and inspect import metadata, state, selected sheet, headers, mapping and counters.
- `PATCH /imports/{id}/mapping` — map canonical fields to exact uploaded column headers, validate every row and return a bounded preview of 25 rows.
- `GET /imports/{id}/rows` — paginated raw/normalized row detail, optionally filtered by `status`.
- `GET /imports/{id}/error-report.xlsx` — tenant-scoped XLSX report for error, duplicate and warning rows.
- `POST /imports/{id}/confirm` — requires `Idempotency-Key`; commits only rows whose state is `valid`.
- `DELETE /imports/{id}` — deletes only pre-commit imports; committed and cancelled imports are immutable.

## State machine

`uploaded` → `parsed` → `mapped` → `validated` → `awaiting_confirmation` → `committed`.

A mapping may be replaced while the import is pre-commit. If no row is valid, the state remains `validated` and confirmation is rejected. `failed` and `cancelled` are terminal states reserved for operational recovery and explicit cancellation workflows. Confirmation outside `awaiting_confirmation` returns 409.

## File handling and security

- The original file is not persisted. Bytes are read in bounded chunks, parsed in memory and then discarded; only the SHA-256 digest, sanitized filename, MIME metadata, headers and parsed row values are stored.
- `UPLOAD_MAX_MB` defaults to 25; `IMPORT_MAX_ROWS` defaults to 100,000; `IMPORT_MAX_COLUMNS` defaults to 200; `IMPORT_MAX_CELLS` defaults to 1,000,000 to cap in-memory expansion. An ASGI middleware enforces the multipart request-body cap before Starlette spools file parts; the route independently checks the file-part byte count.
- Only `.csv` and `.xlsx` are accepted. MIME, extension and XLSX ZIP signature are checked. `.xls`, `.xlsm`, macro projects, external links, encrypted ZIP entries, unsafe archive paths, excessive entry counts, excessive expansion ratio and excessive uncompressed size are rejected.
- XLSX parsing uses `openpyxl` read-only/data-only mode and `defusedxml`; formulas are not evaluated. Hidden sheets are not selectable.
- CSV accepts UTF-8/UTF-8-BOM and Windows-1256, with delimiter detection for comma, semicolon, tab and pipe. NUL bytes, malformed CSV, duplicate/blank headers and over-wide rows are rejected.
- Spreadsheet error reports neutralize formula-like string values to prevent CSV/XLSX formula injection.
- No user-controlled file path is written to disk, served by the API or included in logs.

## Mapping and validation

Product mapping supports `sku`, `name`, `unit`, `description`, `sale_price`, `purchase_cost`, and `is_active`. `sku`, `name`, and `unit` are required. Prices are parsed with `Decimal`, must be nonnegative, fit `NUMERIC(20,2)`, and have no more than two fractional digits. Product units are `piece`, `kg`, `liter`, `meter`, or `box`; Persian unit labels are normalized to those canonical values.

Supplier-price mapping supports `raw_name`, `sku`, `unit_price`, `unit`, and `currency`. `raw_name`, `unit_price`, and `unit` are required. Currency defaults to the tenant currency and any different currency is rejected. Unmatched rows remain unlinked (`product_id = NULL`); no fuzzy or automatic product matching occurs in this step.

Duplicate product SKUs are checked against live products, live variants and earlier rows in the same file. Duplicate supplier SKUs (or raw names when SKU is absent) within one file are skipped. Validation results are stored per row with machine-readable codes and Persian display messages. The preview and summary explicitly distinguish valid, error and duplicate rows.

## Atomic confirmation

Confirmation locks the tenant row before applying product rows, matching the catalog write serialization rule. It also locks the import and valid rows. The idempotency record, domain rows, product price history, audit event and final import state are committed in one database transaction. A failed transaction leaves the import in `awaiting_confirmation` and does not consume the idempotency key, so the same key can safely be retried after the conflict is resolved.

Product imports create new products only; duplicate SKUs are skipped rather than updating existing products. When initial purchase/sale prices are provided, the matching price-history rows are created with source `import` in the same transaction.

Supplier-price imports create a supplier price list with source `import` and status `draft`. A separate explicit `POST /price-lists/{id}/finalize` is required before it can participate in comparisons. Import confirmation never changes `products.purchase_cost` automatically.

## Deliberate limits

- Sales import is deferred until sales-order and sale-item persistence exists.
- Category assignment, automatic product matching, fuzzy matching, unit conversion and foreign-currency conversion are deferred.
- Product imports are insert-only; correction/update workflows are separate.
- Supplier-price import does not attach rows to products. Matching is an explicit later workflow.
- Files are parsed synchronously in the API process. Background jobs and object-storage retention are deferred until measured file volumes justify them.
