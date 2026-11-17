# گزارش Phase 2 / Step 1 — Infrastructure Foundation & Dependency Compatibility

**تاریخ:** ۲۰۲۶-۱۱-۱۶ · **محدوده:** فقط زیرساخت حداقلی Backend/Frontend + ماتریس سازگاری + فایل‌های Docker/CI + مستندات. هیچ قابلیت محصولی، Auth، مدل دامنه، migration یا محاسباتی پیاده نشده.

## ۱) فهرست دقیق فایل‌های ایجادشده و تغییرکرده

**Backend (جدید):**
`backend/pyproject.toml` · `backend/app/core/config.py` · `backend/app/core/db.py` · `backend/app/core/logging.py` · `backend/app/core/errors.py` · `backend/app/core/middleware.py` · `backend/app/main.py` · `backend/app/api/v1/health.py` · `backend/tests/conftest.py` · `backend/tests/unit/test_config.py` · `backend/tests/unit/test_health.py` · `backend/tests/unit/test_errors.py` · `backend/tests/integration/test_db_readiness.py` · `backend/requirements.lock` (۳۸ بسته/۸۵۳ hash) · `backend/requirements-runtime.lock` (۲۲ بسته/۴۴۶ hash) · `backend/Dockerfile` · `backend/.dockerignore`

**Frontend (جدید):**
`frontend/package.json` · `frontend/package-lock.json` (تولید npm) · `frontend/tsconfig.json` + `tsconfig.app.json` + `tsconfig.node.json` · `frontend/vite.config.ts` · `frontend/eslint.config.js` · `frontend/index.html` (fa/RTL) · `frontend/src/index.css` · `frontend/src/main.tsx` · `frontend/src/App.tsx` · `frontend/src/lib/api.ts` · `frontend/src/features/welcome/WelcomePage.tsx` + `WelcomePage.test.tsx` · `frontend/Dockerfile` · `frontend/nginx-default.conf` · `frontend/.dockerignore`

**ریشه (جدید/تغییر):**
`docker-compose.yml` · `Caddyfile` · `.github/workflows/ci.yml` · `SECURITY.md` · `CHANGELOG.md` · `scripts/make_backend_lock.sh` · `scripts/make_phase1_zip.sh` (دور قبل، دست‌نخورده) · `scripts/smoke_backend.sh` · `scripts/start_pg_embedded.py` · `scripts/pydantic_settings_repro.py` · `scripts/resolve_image_digests.py` · `scripts/matrix_smoke/*` (fixtures ماتریس)

**تغییر در فایل‌های موجود:**
`README.md` (بازنویسی: وضعیت + راهنمای PowerShell) · `docs/dependencies.md` (ماتریس اجراشده + Pinned + CVE bumps) · `docs/environment-limitations.md` (بازآزمایی حقایق + ناهنجاری pydantic-settings) · `.env.example` (کلیدهای POSTGRES_*) · `backend/app/modules/**/__init__.py` دست‌نخورده (اسکلت ماژول‌ها از قبل موجود بود و طبق معماری حفظ شد)

**شواهد:** `download/evidence/` — ۱۲ فایل (خروجی واقعی همهٔ گیت‌ها).

## ۲) نسخه‌های نهایی وابستگی‌ها (آزمایش‌شده، exact)

**Backend:** fastapi 0.163.1 · uvicorn 0.54.0 · pydantic 2.12.5 · **pydantic-settings 2.14.2** (2.13.1 → CVE-2026-58203) · SQLAlchemy 2.1.8 · alembic 1.20.1 · psycopg/binary 3.3.9 · httpx 0.28.1 · **pytest 9.0.3** (9.0.2 → PYSEC-2026-1845) · pytest-asyncio 1.3.0 · pytest-cov 7.0.0 · ruff 0.17.5 · mypy 2.4.1 — Python 3.12.16.

**Frontend (در package.json):** react/react-dom 19.3.1 · react-router 7.18.5 · @tanstack/react-query 5.107.1 · tailwindcss + @tailwindcss/vite 4.3.5 · vazirmatn 33.0.3 · vite 8.3.8 · @vitejs/plugin-react 6.3.0 · **typescript 6.0.3** (TS 7.0.2 با شواهد ERESOLVE رد شد) · vitest 5.1.0 · jsdom 31.0.1 · @testing-library/react 16.3.3 · eslint 10.15.0 + typescript-eslint 8.73.0 + react-hooks 7.1.1 + react-refresh 0.5.8.

**ماتریس‌آزموده ولی بی‌مصرف در Step 1 (عمداً خارج از package.json):** react-hook-form 7.92.0 · @hookform/resolvers 7.0.6 · zod 4.6.7 · echarts 6.1.0 · @playwright/test 1.65.1 — همگی در smoke جداگانه نصب/تایپ/build شدند.

**Imageهای Docker (تگ + digest با Registry API راستی‌آزمایی):** python:3.12-slim-bookworm، node:24-alpine، nginxinc/nginx-unprivileged:1.29-alpine، postgres:16-alpine، caddy:2-alpine — digestها در `evidence/image_digests.json` و داخل compose/Dockerfile.

## ۳) خروجی واقعی تست‌های اجراشده

| تست | خروجی واقعی |
|---|---|
| Backend unit (ruff→mypy→pytest) | `All checks passed!` · mypy strict بدون خطا · **۲۱ passed** (evidence/backend_lint_type_test.txt) |
| Backend integration (PG 16.2 واقعی، بدون mock) | **۳ passed** — `SELECT 1` + endpoint ready + live (evidence/backend_integration_tests.txt) |
| Smoke با uvicorn واقعی | بدون DB: live **200**، ready **503**+Retry-After؛ با PG واقعی: ready **200**؛ headers و X-Request-ID و لاگ JSON تأیید (evidence/backend_smoke.txt) |
| Frontend lint/type-check/vitest | LINT OK · TSC OK · **۳ passed (۳ فایل حالت: loading/success/error)** (evidence/frontend_lint_type_test_build.txt) |
| Frontend build + preview | `✓ built in 265ms` — فونت‌های woff2 باندل؛ preview: HTML fa/RTL با HTTP 200 |
| pip-audit 2.10.1 | اول: ۳ آسیب‌پذیری در ۲ بسته → پس از bump: **No known vulnerabilities found** (evidence/pip_audit.txt) |
| npm audit | **found 0 vulnerabilities** (evidence/npm_audit.txt) |
| npm ci در محیط تمیز | موفق (rm node_modules → npm ci → همهٔ گیت‌ها سبز) |
| نصب clean از lock با hash | venv تازه: ۴۰ بسته، import موفق |

## ۴) خروجی واقعی build

- Backend: اجرای واقعی `uvicorn app.main:app` روی پورت‌های 8021/8022 (لاگ‌ها: evidence/uvicorn_phase_a.log، uvicorn_phase_b.log).
- Frontend: `npm run build` → `dist/` (JS 292kB، CSS 7.2kB، woff2های Vazirmatn) + `vite preview` با curl تأیید شد.
- Imageهای Docker: **build نشد** (بند ۵).

## ۵) وضعیت Docker و Compose — صریح

**Docker CLI و daemon در این سندباکس وجود ندارد (تأیید مجدد) — هیچ دستور docker اجرا نشده و هیچ image ساخته نشده.** کارهای انجام‌شده بدون daemon: نوشتن Dockerfileهای non-root دو سرویس + nginx.conf + docker-compose.yml (۴ سرویس، healthcheck واقعی pg_isready/SELECT 1/wget، volume ماندگار، شبکهٔ داخلی، فقط Caddy پورت منتشر می‌کند) + Caddyfile (توسعهٔ HTTP؛ قالب TLS تولیدی جدا و کامنت‌شده) + **راستی‌آزمایی تگ/digest پنج base image از طریق Registry HTTP API** + اعتبارسنجی ساختار YAML و قواعد exposure با اسکریپت (فقط caddy دارای ports). تست واقعی compose = CI و سیستم شما.

## ۶) وضعیت CI — صریح

`.github/workflows/ci.yml` **فقط ساخته شده و هرگز اجرا نشده** (سندباکس runner ندارد). هر ۱۶ مرحلهٔ دستور شامل است: checkout، setup Python 3.12، setup Node 24، نصب از lock (pip با `--require-hashes` / npm ci)، ruff، mypy، unit tests، سرویس PostgreSQL واقعی 16، readiness با PG واقعی (`pytest -m integration`؛ بدون migration/create_all طبق ممنوعیت)، eslint+type-check، vitest، production build، docker build (بدون push) برای هر دو سرویس، pip-audit (با `--require-hashes`)، npm audit، gitleaks. PostgreSQL سرویس با اعتبارنامهٔ موقتی CI است (نه secret واقعی). دو گیت قابل‌مقایسه (pip-audit و npm audit) در همین سندباکس واقعاً اجرا و نتیجه ثبت شد.

## ۷) مشکلات و ریسک‌های باقی‌مانده

1. **pydantic-settings در سندباکس env نمی‌خواند** — با هر سه نسخهٔ آزمایش‌شده (2.12.0/2.13.1/2.16.3) repro شد؛ mitigation: بارگذاری صریح env با init kwargs (رفتار یکسان در همه‌جا)؛ **در CI باید بازآزمایی شود**؛ اگر آنجا منبع env عادی کار کرد، رفتار تغییری نمی‌کند چون بارگذاری صریح است.
2. CI و compose هرگز اجرا نشده‌اند — تا اولین اجرای واقعی، «سبز بودن» ادعا نمی‌شود.
3. TS 7 و react-router 8 عمداً معلق ماندند — ارتقا فقط با PR و اجرای ماتریس.
4. E2E Playwright و CSP دقیق و rate limit: طبق فازهای بعدی security.md §۱۲.
5. گام `docker compose up` کامل و healthcheckهای سبز در سندباکس ممکن نشد — پذیرش نهایی روی سیستم شما طبق Runbook.
6. ناهنجاری جزئی محیط: tracer سندباکس یک warning استاندارد starlette/httpx در pytest می‌دهد (بی‌اثر روی نتایج).

## ۸) دستورات دقیق PowerShell (اجرای محلی)

در README.md بخش «اجراای محلی (Windows PowerShell)» — دو مسیر کامل: (الف) بدون Docker: venv + `pip install -r requirements.lock --require-hashes` + `uvicorn app.main:app --reload --port 8000` + `npm ci` + `npm run dev`؛ (ب) با Docker: `Copy-Item .env.example .env` → پرکردن POSTGRES_PASSWORD → `docker compose up -d --build` → `docker compose ps` → `curl.exe http://localhost:8080/api/health/ready`.

## ۹) درصد پیشرفت واقعی Phase 2

- **Step 1 (دامنهٔ همین دستور): ۱۰۰٪ انجام‌شده** — با دو استثنای صریح بند ۵/۶ (اجرای Docker/CI در سندباکس ناممکن بود؛ فایل‌ها و راستی‌آزمایی‌های بدون daemon انجام شد).
- کل Phase 2: قابل اعلام عددی نیست چون مرز Stepهای بعدی را ممیز تعیین می‌کند؛ با فرض ۴–۵ Step بودن Phase 2، تخمین محافظه‌کارانه ≈ **۲۰–۲۵٪**.

## ۱۰) پیشنهاد مرحلهٔ بعد

**Phase 2 / Step 2 — «راستی‌آزمایی استقرار»:** اجرای CI واقعی روی GitHub (سبز شدن ۱۶ گیت)، اجرای `docker compose up -d --build` روی سیستم شما با جمع‌آوری وضعیت healthcheck هر ۴ سرویس و خروجی `/api/health/ready` از مسیر Caddy، تست مسیر شکست (توقف postgres → ready=503 → restart)، و اگر هر دو سبز شد: ورود به Phase 3 (Alembic + مدل identity/tenancy طبق اسناد تأییدشده) با اولین migration واقعی.

---
**تعهد صریح:** هیچ commit/push/merge انجام نشده (تغییرات در working tree) · هیچ قابلیتی مستندشده به‌عنوان پیاده‌سازی‌شده گزارش نشده · همهٔ «✅»های این گزارش با فایل شواهد در `download/evidence/` پشتیبانی می‌شوند.
