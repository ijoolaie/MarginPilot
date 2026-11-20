# Phase 4 — برنامهٔ پیاده‌سازی دامنه

## Step 1 — Catalog & Supplier Data Foundation

**وضعیت:** پیاده‌سازی و اعتبارسنجی کامل؛ تأیید کاربر دریافت شد.

### محدوده

این گام فقط لایهٔ persistence و schema را برای هفت جدول tenant-owned ایجاد می‌کند:

- `categories`
- `products`
- `product_variants`
- `product_price_history`
- `suppliers`
- `supplier_price_lists`
- `supplier_prices`

تعریف دامنه و قرارداد این جداول در `data-model.md` مرجع اصلی است. API، CRUD، رابط کاربری، import و محاسبات مالی در این گام ساخته نمی‌شوند.

### پیاده‌سازی

- مدل‌های SQLAlchemy 2 در `backend/app/modules/catalog/models.py`.
- Migration افزایشی Alembic با شناسهٔ `f2e7b9429cbe` و وابستگی به `0001_identity_tenancy`.
- FKهای مرکب tenant-aware برای تمام روابط بین رکوردهای tenant-owned.
- کلیدهای یکتای `(tenant_id, id)` برای اهداف FK مرکب؛ کلید سه‌ستونهٔ `(tenant_id, product_id, id)` برای ProductVariant.
- Partial unique indexes برای دسته‌های ریشه/فرزند، SKU زندهٔ محصول و واریانت، و اقلام لیست قیمت تأمین‌کننده.
- قیمت‌ها با `NUMERIC(20,2)` و `Decimal`؛ بدون float.
- `supplier_prices` فاقد `supplier_id` تکراری است؛ تأمین‌کننده از `supplier_price_lists` استخراج می‌شود.
- `product_price_history` برای تغییر قیمت و provenance؛ مقدار مرجع محصول با تأیید لیست قیمت تأمین‌کننده به‌طور خودکار تغییر نمی‌کند.

### محدودیت‌های آگاهانه

- یکتایی SKU بین دو جدول `products` و `product_variants` یک قاعدهٔ سرویس است و با یک unique index سادهٔ بین‌جدولی قابل تضمین نیست؛ باید پیش از فعال‌سازی APIهای نوشتن در Catalog service اجباری و تست شود.
- تطابق `supplier_prices.currency` با `tenants.currency_code` قاعدهٔ سرویس است؛ CHECK بین‌جدولی یا trigger در v1 اضافه نشده است.
- سرویس‌های CRUD، کنترل دسترسی endpointها، Audit رخدادهای دامنه و تاریخچه‌نویسی هنگام تغییر محصول در گام‌های API بعدی پیاده می‌شوند.
- حذف نرم برای محصولات، واریانت‌ها، دسته‌ها و تأمین‌کنندگان است؛ FKهای تاریخی و ارجاعی مانع حذف سخت ناخواسته می‌شوند.

### معیارهای پذیرش

- Migration upgrade، downgrade تا revision قبلی و upgrade مجدد روی PostgreSQL واقعی.
- `alembic check` بدون drift.
- تست FKهای مرکب و جلوگیری از ارجاع بین tenantها.
- تست partial unique indexes، بازاستفاده از SKU/نام پس از soft delete و یکتایی اقلام لیست قیمت.
- تست CHECKها، provenance قیمت و دقت Decimal.
- Ruff، mypy، unit tests و integration tests سبز.
- هیچ تغییر در Auth/Tenancy، Docker سراسری، منابع سایر پروژه‌ها یا شاخهٔ main.

## گام‌های بعدی

Step 1 تأیید شده است؛ Step 2 در ادامهٔ همین سند تعریف و پیاده‌سازی شده است. واردکردن Excel و مقایسهٔ قیمت‌ها مراحل جداگانه‌اند.

## Step 2 — Catalog & Supplier Services and APIs

**Status:** Implemented locally, validated, and approved by the user.

### محدودهٔ پیاده‌سازی

- API دسته‌ها: فهرست، ایجاد، ویرایش و حذف نرم؛ جلوگیری از چرخه در parent chain و جلوگیری از حذف دستهٔ دارای محصول/فرزند زنده.
- API محصولات: فهرست صفحه‌بندی‌شده و فیلترپذیر، ایجاد، جزئیات، ویرایش، حذف نرم و تاریخچهٔ قیمت خرید/فروش.
- API واریانت: ایجاد و نمایش واریانت‌های زنده در جزئیات محصول.
- یکتایی SKU بین products و product_variants با قفل ردیف tenant و تراکنش؛ unique indexهای درون‌جدولی همچنان پشتیبان DB هستند.
- API تأمین‌کنندگان: فهرست، ایجاد، ویرایش و حذف نرم.
- ایجاد لیست قیمت دستی به‌صورت draft، مشاهدهٔ لیست/اقلام، نهایی‌سازی draft غیرخالی و حذف صرفاً draft؛ لیست final تغییرناپذیر است.
- قیمت‌های هر ردیف با Decimal و ارز tenant اعتبارسنجی می‌شوند؛ SKU/raw_name تکراری در یک لیست رد می‌شود.
- اقدام صریح `purchase-cost-from-supplier-price` فقط از ردیف final، هم‌ارز و هم‌واحد؛ تغییر محصول، تاریخچهٔ provenance و Audit در یک تراکنش ثبت می‌شوند.
- فیلتر و تاریخچهٔ قیمت تأمین‌کننده و endpoint کمترین قیمت؛ فقط ردیف final، هم‌ارز tenant و هم‌واحد محصول قابل مقایسه است.
- همهٔ routeها با `TenantContext` و مجوزهای موجود `product:*` و `supplier:*` محافظت می‌شوند؛ Audit در عملیات نوشتن ثبت می‌شود.

### اصلاح تکمیلی مدل واحد قیمت تأمین‌کننده

بازبینی پیاده‌سازی API یک شکاف واقعی در مدل مصوب را نشان داد: `supplier_prices` واحد قیمت نداشت، در حالی که قرارداد `lowest-price` باید واحدهای ناهم‌ارز را حذف و گزارش کند. برای جلوگیری از مقایسهٔ اشتباه، migration افزایشی `a7c19d4e6f20` ستون `unit` و CHECK واحدهای مجاز را اضافه می‌کند. ستون برای سازگاری با ردیف‌های قدیمی nullable است؛ API جدید برای هر آیتم unit می‌خواهد. ردیف متصل به محصول می‌تواند واحد متفاوت داشته باشد تا منبع داده از بین نرود، اما در `lowest-price` وارد مقایسه نمی‌شود و واحدش در `excluded_units` می‌آید. اقدام تنظیم بهای مرجع نیز فقط ردیف هم‌واحد را می‌پذیرد.

### مرزهای آگاهانه

- نهایی‌سازی لیست قیمت هیچ‌گاه `products.purchase_cost` را خودکار تغییر نمی‌دهد.
- ردیف قیمت تأمین‌کننده با `product_id=null` در مقایسهٔ یک محصول شرکت نمی‌کند تا زمان تطبیق صریح.
- تبدیل واحد، تبدیل ارز خارجی، import Excel/CSV، تطبیق خودکار، comparison runs، UI و سایر ماژول‌های دامنه خارج از Step 2 هستند.
- حذف supplier یا product نرم است؛ تاریخچه و لیست‌های قیمت حفظ می‌شوند.
- لیست final immutable است؛ برای اصلاح اشتباه، باید یک لیست جدید ساخته شود.

### معیارهای پذیرش

- تست API روی PostgreSQL واقعی برای RBAC، جداسازی tenant، CRUD، soft delete، چرخهٔ دسته، SKU بین‌جدولی، Decimal و تاریخچهٔ قیمت.
- تست supplier price list برای currency/unit mismatch، duplicate items، draft deletion، finalization، immutable final، lowest-price و provenance.
- migration upgrade/downgrade/upgrade و `alembic check` بدون drift.
- اجرای کامل unit و integration tests، Ruff، mypy و `pip check`.
- عدم تغییر Docker سراسری، منابع پروژه‌های دیگر، main یا remote بدون مجوز.
## Step 3 — CSV/XLSX Import Pipeline

**Predecessor:** Phase 4 Step 2 is approved by the user.

**Status:** Implemented locally, validated, and approved by the user.

### Delivered

- Tenant-scoped `imports` and `import_rows` persistence with composite tenant FK, JSONB checks, state constraints, row uniqueness and indexes.
- Bounded CSV/XLSX upload, parser hardening, UTF-8/Windows-1256 handling, delimiter detection, visible-sheet selection, macro/external-link/zip-bomb defenses and formula-safe error reports.
- Two-phase upload → mapping/validation → explicit confirmation flow for products and supplier prices.
- Decimal-only price normalization, unit/currency validation, duplicate classification, paginated row inspection and bounded preview.
- Atomic, idempotent confirmation; product price-history provenance; supplier price list creation as draft; audit events.
- Sales import intentionally remains disabled until sales-domain persistence is delivered.

### Acceptance evidence

- PostgreSQL fresh upgrade, downgrade/upgrade and `alembic check`.
- Unit tests for CSV encodings/delimiters, XLSX parsing, archive hardening, mappings, Persian digits/units, Decimal validation, duplicates and spreadsheet formula injection.
- Integration tests for product and supplier imports, preview, row errors, error report, tenant isolation, RBAC, idempotent replay, rollback/retry, XLSX upload and draft finalization.
- Ruff, strict mypy, `pip check`, and the full backend test suite.

### Security and operational boundaries

- Original upload bytes are not persisted; only parsed rows and file metadata/digest are stored.
- Runtime dependencies `openpyxl`, `defusedxml` and `python-multipart` are pinned and hash-locked.
- Upload defaults: 25 MB, 100,000 rows, 200 columns, 1,000,000 total cells; ZIP limits are enforced by the parser.
- No Docker global configuration, other project resources, main branch or remote Git state is changed by this step.
