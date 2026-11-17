# گزارش Phase 1 — معماری و ساختار پروژه (MarginPilot)

**تاریخ:** ۲۰۲۶-۱۱-۱۶ · **وضعیت:** COMPLETED (فقط طراحی — طبق شرط E هیچ قابلیتی پیاده نشده) · **اقدام بعدی:** توقف برای تأیید Phase 2

## فایل‌های ایجادشده

| فایل | نقش |
|---|---|
| `docs/architecture.md` | لایه‌ها، چرخهٔ درخواست، ساختار پوشه‌ها، قرارداد بین‌ماژولی، قوانین وابستگی (۱۶۶ خط) |
| `docs/data-model.md` | ERD (۳۵ رابطه)، ۲۳ جدول، enumها، indexها، یکپارچگی مالی (۱۴۳ خط) |
| `docs/api-contract.md` | ~۵۰ endpoint در ۱۳ گروه، طرح خطای یکسان، pagination/sort/idempotency (۱۹۳ خط) |
| `docs/security.md` | جریان نشست/CSRF/tenant isolation/RBAC/آپلود امن + نگاشت OWASP Top 10 (۱۱۶ خط) |
| `docs/testing-strategy.md` | هرم تست، تقسیم محیط‌ها، E2E ده‌مرحله‌ای، CI gates (۵۷ خط) |
| `docs/calculation-principles.md` | Decimal، گرد کردن half-up، largest-remainder، ۱۴ بردار مرجع (۸۱ خط) |
| `docs/decisions.md` | ۱۷ ADR با دلیل/جایگزین/هزینهٔ تغییر (۸۶ خط) |
| `docs/dependencies.md` | سیاست pin + ماتریس سازگاری + استعلام registry (۶۶ خط) |
| `docs/environment-limitations.md` | سندباکس/CI/محلی + Runbook پذیرش (۴۵ خط) |
| `README.md` | نمای پروژه و فهرست سندها |
| `.env.example` | قالب متغیرهای محیطی، همه placeholder، بدون Secret |
| `.gitignore` | کامل‌سازی (env، pycache، venv، dist، coverage و…) |
| `backend/**` | اسکلت ۱۷ پکیج خالی (`__init__.py`) مطابق معماری — بدون هیچ کد قابلیت |

## تغییرات Git (مطابق اصلاحیه A)

- اسکن کامل تاریخچه: `.env` فقط در commit اولیه با `DATABASE_URL=file:...` بوده است؛ **هیچ Secret واقعی در تاریخچه یافت نشد** → پاک‌سازی تاریخچه لازم نیست.
- `git rm --cached .env` اجرا شد (staged deletion، فایل روی دیسک باقی است)؛ `.gitignore` اکنون `.env*` را با نگه‌داشتن `!.env.example` می‌پوشاند.

## تصمیمات معماری (خلاصه — کامل در docs/decisions.md)

Modular Monolith تک‌ریپویی · FastAPI+SQLAlchemy 2+Alembic+PostgreSQL 16 · نشست opaque در Postgres · tenant در shared schema با scoping اجباری · پول Decimal/NUMERIC(20,2) بدون تبدیل ضمنی · گرد کردن half-up در نقاط R1/R2/R3 · موتور محاسبه خالص + formula_version · import دو مرحله‌ای · RBAC در DB · rate limit درون‌حافظه‌ای (Redis-ready) · SPA بدون SSR · Pandas · billing فقط Adapter · PK عددی · Integration CI-first با Postgres واقعی · زبان‌ها طبق تصمیم ۵ شما · pin محافظه‌کارانه.

## مدل ERD

۲۳ جدول در ۵ خوشه: هویت/امنیت (users, tenants, memberships, roles, permissions, role_permissions, sessions, password_reset_tokens, audit_logs) · کاتالوگ (categories, products, product_variants, suppliers, supplier_price_lists, supplier_prices) · فروش/هزینه (sales_orders, sale_items با cost snapshot و cost_source، expenses) · ورود داده (imports, import_rows) · محاسبه/گزارش/مقایسه (calculations, reports, comparison_runs, comparison_matches, tenant_settings). دیاگرام کامل: `docs/data-model.md §۲`.

## قرارداد API

`/api/v1` با ۱۳ گروه (auth, tenants/memberships, users, products, suppliers, sales, expenses, imports, pricing, comparison, analytics, reports, settings/health)، طرح خطای یکسان با ۱۳ کد، pagination/sort whitelist، Idempotency-Key روی confirm/report، RBAC با کد مجوز در هر endpoint.

## جریان‌های امنیتی

نشست: توکن تصادفی + هش SHA-256 در DB، کوکی HttpOnly/Secure/SameSite=Lax، انقضای idle+absolute، ابطال فوری · CSRF: double-submit + Origin check · Tenant: Context سه‌لایه + 404 متقاطع · Brute force: rate limit + قفل تدریجی · آپلود: magic bytes، رد ماکرو/xlsm، ضد zip-bomb، حذف خودکار temp · OWASP Top 10 نگاشت کامل به کنترل‌ها.

## وابستگی‌ها

استعلام واقعی از PyPI/npm انجام شد؛ pin در Phase 2 پس از ماتریس سازگاری (TS7↔Vite8، RHF↔Zod4، Playwright revision). هیچ نصبی در Phase 1 انجام نشد (شرط E).

## تست‌ها و راستی‌آزمایی اجراشده در این Phase (شواهد)

1. `git ls-files | grep -c '^\.env$'` → **0** (خروج از tracking موفق)
2. اسکن Secret در کل تاریخچه → **NO_SECRET_PATTERN_FOUND** (فقط واژه‌های گزارش)
3. اسکن Secret در فایل‌های جدید → **CLEAN**
4. اسکن placeholder (【/TODO/XXX) → تنها یک hit کاذب (واژهٔ NaN در توضیح رفتار موتور) → CLEAN
5. توازن code fence همهٔ سندها → EVEN ✓
6. `python3 -m compileall backend` → **COMPILEALL_OK** (اسکلت پکیج‌های Python معتبر)
7. ERD: ۳۵ رابطه، ۲۳ جدول، همه در سند ✓

**تست محصولی در این Phase وجود ندارد** — طبق شرط E، unit/integration از Phase 3 به بعد با کد واقعی ساخته می‌شود.

## ریسک‌های باقی‌مانده

R1 اجرای compose/AC#1 فقط در CI/محلی (بدون Docker در سندباکس) · R2 Integration فقط با Postgres واقعی CI (پلن B: embedded-postgres در Phase 3) · R6 ماتریس سازگاری TS7/Zod4 هنوز اجرا نشده (Phase 2) · R4 PDF فارسی باید در ابتدای Phase 11 پروتوتایپ شود · تصمیم‌های باز: none — همهٔ ۶ تصمیم شما در سندها ثبت شد.

## قالب بخش ۱۸

- **Phase:** 1 — Architecture and Project Structure
- **Status:** COMPLETED (فقط طراحی)
- **Completed Tasks:** ۹ سند طراحی + اصلاحات A + اسکلت backend + راستی‌آزمایی
- **Created Files:** ۱۳ مورد جدول بالا (+ همین گزارش)
- **Modified Files:** `.gitignore` (به‌روزرسانی)، Git index (untrack `.env`)
- **Tests Executed / Passed / Failed:** ۷ بررسی بالا / ۷ / 0 (بدون تست محصولی)
- **Security Findings:** بدون یافتهٔ جدید؛ یافتهٔ قبلی (.env tracked) **رفع شد** (untracked + gitignore + بدون Secret در تاریخچه)
- **Known Limitations:** بدون Docker/PG در سندباکس؛ pin نسخه‌ها به Phase 2 موکول است
- **Acceptance Criteria (Phase 1):** طراحی معماری/ساختار/قراردادها/مدل داده/قرارداد API/امنیت/تست با دلیل و جایگزین (شرط F) — ✅ همه در docs/
- **Evidence:** خروجی ۷ بررسی بالا + محتوای سندها
- **Next Phase:** Phase 2 — Docker and Infrastructure (**توقف؛ در انتظار تأیید شما**)

## وضعیت قابلیت‌ها

همهٔ ماژول‌های محصول (Auth، Tenancy، RBAC، Product، Supplier، Sales، Expenses، Import، Comparison، Calc Engine، Analytics، Report، Billing، Frontend، Docker/CI) همچنان **NOT STARTED**؛ «معماری و سند طراحی» = IMPLEMENTED/راستی‌آزمایی‌شده (docs + اسکلت).
