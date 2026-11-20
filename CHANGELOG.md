# Changelog

قالب تقریبی Keep a Changelog؛ نسخه‌گذاری فاز محور (SemVer از v1.0.0 محصول شروع می‌شود).

## [phase2-step1-r1] — 2026-11-16 — Independent Review Corrections (Round 1)

### Fixed
- **P1-01**: `.env` پیش‌فرض نسبت به ریشهٔ پروژه resolve می‌شود (`PROJECT_ROOT` از `__file__`؛ `config.py`) نه CWD — اجرای uvicorn از `backend/` فایل ریشه را می‌خواند؛ اولویت env var بر فایل حفظ و با ۴ تست جدید پوشش داده شد.
- **P1-02**: فقط `postgresql+psycopg://` مجاز است؛ `postgresql://` صریحاً رد می‌شود (پیام خطا + کامنت هماهنگ) و گارد دفاعی دوم در `db.build_engine` هم psycopg2-fallback را غیرممکن می‌کند (تست dialect + رد scheme).
- **P1-03**: ترتیب middleware اصلاح شد: RequestContext اکنون بیرونی‌ترین است (CORS → GlobalExceptionHandler داخل آن). روی 500 واقعی (تست با route عمداً خراب): `X-Request-ID` در header، `request_id` غیر NULL و همبسته در error body، Security Headers، و access-log با همان request_id — همه تضمین و تست می‌شوند؛ هیچ جزئیات داخلی در Response نیست.
- **P1-04**: `/health/ready` از `async def` به `def` تبدیل شد (اجرای threadpool برای `SELECT 1` همگام)؛ تست جدید نشان می‌دهد DBِ کند (sleep 1s) مسیر `/health/live` را بلاک نمی‌کند.
- **P2-01**: سرویس PostgreSQL در CI به همان digest تأییدشدهٔ Compose پین شد (`image_digests.json`).
- **P2-02**: Vite dev server روی پورت 3000 با `strictPort` قفل شد (هماهنگ با APP_BASE_URL/CORS_ORIGINS)؛ راهنمای PowerShell اصلاح شد.
- **P2-03**: healthcheck واقعی Caddy اضافه شد: endpoint `/healthz` (respond مستقیم Caddy) + `wget` موجود در image alpine؛ هر ۴ سرویس healthcheck دارند.
- **P2-04**: قاعدهٔ URL-safe بودن `POSTGRES_USER/PASSWORD/DB` در Compose/README/.env.example صریح مستند شد + فرمان تولید رمز امن (hex 192-bit)؛ هیچ secret واقعی وارد repo نشده.
- **P2-05**: فرمت‌کن‌های لاگ خروجی نهایی (پیام + traceback) را با `secret_fragments` (DSN و password) scrub می‌کنند (`[REDACTED]`)؛ request_id حفظ می‌شود؛ تست عدم افشا در لاگ اضافه شد.
- **P2-06**: شمارش واقعی lock ها تصحیح شد: `requirements.lock` = ۳۸ بسته/۸۵۳ hash (قبلاً ۳۹ اشتباه)؛ `requirements-runtime.lock` = ۲۲ بسته/۴۴۶ hash.

### Changed
- تست‌ها: ۲۱ → **۳۶ unit test** (۵ فایل) + ۳ integration؛ شواهد رِ-رِان در `download/evidence/*_r1.txt` (ruff/mypy/pytest/PG واقعی/lint/type/vitest/build/dev-port 3000).

## [phase2-step1] — 2026-11-16 — Infrastructure Foundation & Dependency Compatibility

### Added
- Backend foundation (Python 3.12 + FastAPI): تنظیمات محیطی fail-fast (`pydantic-settings`)، engine SQLAlchemy 2 + بررسی اتصال واقعی (`SELECT 1`)، لاگ ساختاری JSON با request_id، middleware امنیتی، Error Schema یکسان (api-contract §۲)، `GET /health/live` و `GET /health/ready` (مسیر موفق/شکست واقعاً تست شد).
- Backend تست‌ها: ۲۱ unit test + ۳ integration test با PostgreSQL 16.2 واقعی (embedded، بدون mock)؛ smoke با uvicorn واقعی (live=200، ready=503 بدون DB، ready=200 با DB).
- Lock files با hash: `backend/requirements.lock` (full) و `backend/requirements-runtime.lock` (image) — نصب clean با `--require-hashes` در venv تازه تأیید شد.
- Frontend foundation: React 19 + TypeScript + Vite 8 + Tailwind 4 + React Router 7 + TanStack Query 5، فارسی RTL، فونت Vazirmatn self-host؛ صفحهٔ خوش‌آمد با سه حالت وضعیت Backend؛ ۳ تست Vitest؛ production build موفق.
- Docker: `backend/Dockerfile` (non-root، runtime-only hashed lock)، `frontend/Dockerfile` (multi-stage → nginx unprivileged)، `docker-compose.yml` (۴ سرویس، healthcheck واقعی، volume، شبکهٔ داخلی، فقط Caddy منتشرشده)، `Caddyfile` (توسعهٔ HTTP؛ TLS تولیدی جدا)، تگ‌های base image با digest راستی‌آزمایی‌شده.
- CI: `.github/workflows/ci.yml` با ۱۶ مرحلهٔ الزامی + سرویس PostgreSQL واقعی (فایل — هنوز اجرا نشده).
- مستندات: README، dependencies.md (ماتریس اجراشده + CVE bumps)، environment-limitations.md، SECURITY.md، همین فایل.
- `.env.example`: کلیدهای `POSTGRES_USER/PASSWORD/DB` برای compose اضافه شد.

### Changed
- `docs/dependencies.md`: ستون Pinned پر شد؛ دو انحراف امنیتی/سازگاری ثبت شد (pydantic-settings 2.13.1→2.14.2 با CVE-2026-58203؛ pytest 9.0.2→9.0.3 با PYSEC-2026-1845؛ TypeScript 7→6.0.3 با شواهد ERESOLVE).

### Security
- ارتقای امنیتی دو بسته طبق خروجی pip-audit؛ بازتولید lock با hash؛ audit مجدد → پاک.
- headers، non-root، بستن پورت DB/backend، ممنوعیت secret در image/log — جزئیات در SECURITY.md.

### Not done (صریح)
- هیچ Authentication/RBAC/Tenant/مدل دامنه/CRUD/migration/محاسبه/Import/گزارشی پیاده نشده (ممنوعیت Step 1).
- CI فقط فایل است — اجرا نشده؛ `docker compose up` در سندباکس ممکن نبود (بدون daemon) — تست آن در CI/محلی شما.

## [phase1] — 2026-11-16
- معماری کامل مستندشده (۱۱ سند، ۲۴ ADR، مدل دادهٔ ۲۹ جدولی، قرارداد API، امنیت، تست) + ۵ دور بازبینی مستقل و اصلاح؛ بدون هیچ پیاده‌سازی (طبق محدودهٔ Phase 1).

## [phase0] — 2026-11-16
- ممیزی محیط، نقشهٔ فازها، قواعد همکاری (گزارش‌های PDF/DOCX در download/).


## [mvp-roadmap-alignment] — 2026-11-20 — Mini-SaaS MVP scope alignment

### Changed
- ثبت تصمیم اجرایی مصوب برای تمرکز بر تحویل سریع MVP و جلوگیری از overengineering در `docs/mvp-roadmap.md`.
- فازهای باقی‌مانده در چهار بستهٔ محصولی جمع‌بندی شدند: Phase 5 Sales & Expenses، Phase 6 Financial Calculation Engine، Phase 7 MVP UI/Dashboard/Reports و Phase 8 Release Readiness.
- وضعیت README از شرح قدیمی Phase 2 به وضعیت واقعی تحویل‌های Phase 3 و Phase 4 به‌روزرسانی شد.
- مرز میان قابلیت طراحی‌شده و قابلیت واقعاً پیاده‌سازی‌شده صریح شد؛ Sales/Expenses، محاسبات سود، UI محصول و گزارش‌های نهایی همچنان کارهای باقی‌مانده‌اند.

### Deferred from MVP
- Microservices، صف و پردازش توزیع‌شدهٔ پیچیده، حسابداری کامل، انبارداری جامع، گزارش‌ساز سفارشی، AI مالی، اپ موبایل و مقیاس‌پذیری سازمانی تا اثبات نیاز واقعی به تعویق افتادند.

### Non-negotiable
- Tenant isolation، RBAC، صحت مالی Decimal/NUMERIC، تست PostgreSQL واقعی، audit و session security، CI/security scans و backup/restore آزموده‌شده حفظ می‌شوند.
