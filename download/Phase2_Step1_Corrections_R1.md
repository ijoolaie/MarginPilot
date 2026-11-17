# گزارش اصلاحات ممیزی مستقل — Round 1 (Phase 2 / Step 1)

**تاریخ:** ۲۰۲۶-۱۱-۱۶ · **محدوده:** فقط P1-01…P1-04 و P2-01…P2-06 طبق ممیزی — **بدون** شروع Phase 2 / Step 2 یا Phase 3، بدون Auth/Tenant/مدل دامنه/migration، بدون قابلیت محصولی جدید، بدون تغییر معماری، بدون commit/push/merge، بدون تغییر فایل‌های نامرتبط.

**نتیجهٔ گیت‌ها پس از اصلاحات (اجرای واقعی، شواهد کامل در `download/evidence/*_r1.txt`):**
Ruff ✓ (0 خطا) · mypy strict ✓ (22 فایل) · pytest **36 unit + 3 integration با PostgreSQL 16.2 واقعی** ✓ · smoke uvicorn (live 200 / ready 503) ✓ · ESLint ✓ · tsc ✓ · Vitest 3 ✓ · production build ✓ · dev-server روی پورت 3000 ✓ (HTTP 200).

---

## P1-01 — مسیر `.env` نسبت به ریشهٔ پروژه ✅

**تغییرات:**
- `backend/app/core/config.py:44-47` — `PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]` و `DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"`: مسیر از **محل خود فایل** محاسبه می‌شود، نه CWD. اجرای uvicorn از `backend/` فایل `.env` ریشه را می‌خواند (همان‌که README می‌گوید). در کانتینر مسیر به `/.env` ختم می‌شود که وجود ندارد → پیکربندی فقط از environment variables (روش compose) — رفتار مستند در docstring `config.py:11-22`.
- `backend/app/core/config.py:126-130` — `load_settings(env_file=...)` برای تست‌ها دست‌نخورده ماند (ارسال env_file سفارشی حفظ شد).
- اولویت Environment Variables بر فایل: منطق `{**file_values, **dict(os.environ)}` در `config.py:133-135` حفظ شد و با تست جدید صریحاً راستی‌آزمایی می‌شود.
- docstring ماژول (`config.py:11-22`) رفتار واقعی را توضیح می‌دهد.

**تست‌های جدید (`backend/tests/unit/test_config.py:120-172`، کلاس `TestEnvFileResolution`):**
1. `test_default_env_file_is_project_root` — DEFAULT_ENV_FILE مطلق و برابر `<repo-root>/.env` است حتی وقتی CWD به tmp تغییر می‌کند.
2. `test_running_from_backend_reads_root_env_file` — اجرا با CWD خالی، مقدار `DB_POOL_SIZE=7` از فایل «ریشه» خوانده می‌شود.
3. `test_environment_overrides_file_values` — env var بر فایل مقدم است.
4. `test_missing_default_file_is_not_fatal` — بدون .env (CI/کانتینر) env alone کافی است.
- علاوه بر این، `test_missing_database_url_raises` و `test_cache_reset` با fixture `isolated_env_file` مقاوم شدند تا `.env` واقعی توسعه‌دهنده نتواند نتیجهٔ تست را عوض کند.

**شاهد اجرا:** `download/evidence/backend_lint_type_test_r1.txt` (36 passed) و smoke واقعی از پوشهٔ backend در `backend_smoke_r1.txt`.

## P1-02 — فقط `postgresql+psycopg://` ✅

**تغییرات:**
- `backend/app/core/config.py:40` — ثابت `PSYCOPG_SCHEME` جایگزین `ALLOWED_DATABASE_SCHEMES` شد؛ فهرست قبلی به‌اشتباه `postgresql://` را هم می‌پذیرفت.
- `backend/app/core/config.py:88-101` — validator: هر URL غیر از `postgresql+psycopg://` رد می‌شود؛ پیام خطا صریحاً می‌گوید «postgresql:// رد می‌شود: به psycopg2 DBAPI برمی‌گردد»؛ کامنت هم دقیقاً همین را توضیح می‌دهد (هماهنگی پیام/کامنت/رفتار).
- `backend/app/core/db.py:22-35` — گارد دفاعی دوم در `build_engine`: حتی اگر مسیر اوّل دور زده شود، psycopg2-fallback غیرممکن است.
- psycopg2 در هر دو lock وجود ندارد (`grep psycopg backend/requirements*.lock` → فقط psycopg 3.3.9 و psycopg-binary 3.3.9) — dialect واقعی engine با تست تأیید می‌شود: `engine.dialect.driver == "psycopg"`.

**تست‌های جدید:**
- `backend/tests/unit/test_config.py:51-63` — رد `postgresql://` با پیام «psycopg2» و پذیرش scheme مجاز.
- `backend/tests/unit/test_db.py:13-33` — dialect واقعی psycopg3؛ رد `postgresql://` و رد `postgresql+psycopg2://` در سطح engine (با `Settings.model_construct` تا گارد db.py مستقل از validator تست شود).

## P1-03 — ترتیب Middleware و تضمین‌های 500 ✅

**تغییرات:**
- `backend/app/main.py:41-58` — ترتیب ثبت اصلاح شد. در Starlette آخرین `add_middleware` بیرونی‌ترین است؛ ترتیب جدید: **RequestContext → CORS → GlobalExceptionHandler → routes**. کامنت `main.py:41-48` قرارداد و دلیل را مستند می‌کند و هشدار «do not reorder» دارد؛ `middleware.py:1-7` همین قرارداد را تکرار می‌کند.
- قبلاً GlobalExceptionHandler بیرون از RequestContext بود: روی 500 واقعی، پاسخ بدون `X-Request-ID` و بدون Security Headers از RC عبور نمی‌کرد (RC با re-raise خروج می‌شد).

**تست جدید (`backend/tests/unit/test_request_lifecycle.py`) — route عمداً خراب (`_boom` با DSN ساختگی در پیام خطا):**
- `test_500_carries_request_id_security_headers_and_no_leak` (`:35-66`): چهار تضمین هم‌زمان — ①`X-Request-ID` معتبر در header، ②`request_id` غیر NULL در body و **برابر header**، ③Security Headers کامل (nosniff/DENY/CSP/Referrer-Policy)، ④هیچ نشتی: نه SECRET، نه DSN، نه نام کلاس Exception، نه Traceback در Response.
- `test_500_request_id_matches_across_header_and_body` (`:68-73`): یکتایی و همبستگی request_id بین دو درخواست.
- `TestAccessLogOn500.test_access_log_correlated_and_redacted` (`:71-112`): access-log همان مسیر با `status=500` و **همان request_id پاسخ**؛ خروجی لاگ (پیام + traceback) فاقد DSN/password و شامل `[REDACTED]`.

## P1-04 — readiness همگام و بدون بلاک کردن Event Loop ✅

**تغییرات:**
- `backend/app/api/v1/health.py:22-24` — `async def ready()` → `def ready()`: FastAPI توابع sync را در threadpool اجرا می‌کند؛ چون `check_database_connection` همگام/بلاک‌کننده است، فراخوانی آن روی event loop رفتار غلط بود. کامنت دلیل را مستند می‌کند. رفتار 200/503 و اتصال واقعی PostgreSQL حفظ شده (integration رِ-رِان شد).

**تست جدید (`backend/tests/unit/test_health.py:77-107`، `TestReadyDoesNotBlockEventLoop`):** `check_database_connection` با sleep واقعی ۱ ثانیه جایگزین می‌شود؛ سپس `/health/ready` شروع و بعد از 150ms `/health/live` فراخوانی می‌شود — assertion: پاسخ liveness در کمتر از 0.7s برمی‌گردد (اگر handler بلاک‌کننده روی loop اجرا می‌شد، ≥1s می‌شد) + هر دو پاسخ نهایی 200.

## P2-01 — digest یکسان CI و Compose ✅

- `.github/workflows/ci.yml:19-21` — سرویس PostgreSQL: `image: postgres:16-alpine@sha256:81e77a4833487b8132fe4b00bedd39dc3f74b8641e387f19312a48f7de218c2e` — دقیقاً همان digest در `docker-compose.yml:8` و `download/evidence/image_digests.json` (tag 16-alpine).

## P2-02 — پورت Frontend ✅

- `frontend/vite.config.ts:8-21` — `server.port: 3000` + `strictPort: true`: اگر 3000 اشغال باشد Vite با خطا متوقف می‌شود، بی‌صدا جابجا نمی‌شود. با `APP_BASE_URL` و `CORS_ORIGINS` در `.env.example` (`:8-9`، `:55`) هماهنگ.
- **اجرای واقعی:** `npm run dev` → `Local: http://localhost:3000/` و `GET /` → HTTP 200 (شاهد: `frontend_gates_r1.txt`).
- README راهنمای PowerShell (`README.md:56-60`) اصلاح شد: رفتار strictPort و نکتهٔ پورت ثابت.

## P2-03 — healthcheck واقعی Caddy ✅

- `Caddyfile:9-14` — endpoint `handle /healthz { respond 200 }`: Caddy خودش پاسخ می‌دهد، بدون وابستگی به upstream.
- `docker-compose.yml:75-84` — healthcheck سرویس caddy: `wget -q -O /dev/null http://127.0.0.1:8080/healthz`. ابزار: `wget` از busybox که در پایهٔ alpine image صوری caddy موجود است (همان ابزاری که healthcheck فرانت‌اند از آن استفاده می‌کند).
- حالا هر ۴ سرویس healthcheck معتبر دارند: postgres (`pg_isready`)، backend (urllib روی `/health/ready` واقعی)، frontend (wget صفحهٔ nginx)، caddy (wget `/healthz`).
- توجه صادقانه: اجرای واقعی compose در سندباکس ممکن نبود (daemon ندارد — محدودیت مستند)؛ اعتبار ساختار با تست‌های سطح واحد و امکان‌سنجی ابزار پوشش داده شد.

## P2-04 — password در DATABASE_URL ✅

- **تحلیل:** compose URL را با استرینگ اینترپولیشن می‌سازد (`docker-compose.yml:37-41`، کامنت `:33-36`)؛ کاراکترهای ویژه (`@ : / ? # % & = +` و فاصله) URL را خراب می‌کنند و Compose امکان percent-encode ندارد.
- **راه‌حل انتخابی:** محدودیت URL-safe صریح + روش تولید امن (مستند در README بخش «قاعدهٔ رمز URL-safe (P2-04)» و `.env.example:28-38`): فقط حروف/ارقام/`-_.~`؛ تولید رمز ۱۹۲-بیتی با `$b=[byte[]]::new(24); [Security.Cryptography.RandomNumberGenerator]::Fill($b); ($b|%{$_.ToString('x2')}) -join ''` (PowerShell) یا `openssl rand -hex 24` (bash).
- هیچ password واقعی/secret وارد repository نشده — `.env` فقط در worktree sandbox است و git-ignored و خارج از ZIP (گارد فاز قبل حفظ شد).

## P2-05 — عدم افشای Secret در لاگ ✅

**تغییرات (`backend/app/core/logging.py`):**
- `:30-38` — `REDACTED` و `redact_secrets()`.
- `:41-48` — `secret_fragments(settings)`: کامل DSN + password آن (استخراج با `urlsplit`) — چون متن exception ممکن است هر کدام را جداگانه در بر بگیرد.
- `:51-82` — `JsonFormatter` و `ConsoleFormatter` پارامتر `secrets` می‌گیرند و **خروجی نهایی** (پیام رکورد + `formatException`) را scrub می‌کنند؛ نقطهٔ scrub آخرین نقطه است پس برای همهٔ loggerها اعمال می‌شود.
- `:103-114` — `configure_logging` فرگمنت‌ها را از Settings می‌سازد و به فرمت‌کن می‌دهد.
- مسیر خطای DB خودش قبلاً امن بود و ماند: `db.py:85-92` فقط `type(exc).__name__` را لاگ می‌کند (بدون پیام exception).
- request_id correlation دست‌نخورده: scrub فقط متن را عوض می‌کند، نه contextvar را.

**تست‌ها:** `TestAccessLogOn500` (فوق — لاگ واقعی 500 بدون SECRET/DSN با `[REDACTED]`) و `TestRedactionUnit` (`test_request_lifecycle.py:115-146`) — scrub پیام و traceback در سطح formatter؛ `request_id` حفظ شده.

## P2-06 — شمارش واقعی Lock ها ✅

- شمارش با regex `^[A-Za-z0-9][A-Za-z0-9._-]*==` روی خود فایل‌ها: **`backend/requirements.lock` = ۳۸ بسته / ۸۵۳ hash** و **`backend/requirements-runtime.lock` = ۲۲ بسته / ۴۴۶ hash**. عدد قبلی «۳۹» حاصل شمرده‌شدن یک خط کامنت حاوی `==` با `grep -c` بود — اصلاح شد در `download/Phase2_Step1_Report.md:8` و `docs/dependencies.md:40` (روش شمارش ثبت شد؛ تعداد hashها جداگانه: ۸۵۳ و ۴۴۶).

---

## وضعیت واقعی Docker و CI (اعلام صریح)

- **Docker:** Dockerfileها، `docker-compose.yml` و `Caddyfile` **فقط ساخته/اصلاح شده‌اند و هرگز اجرا نشده‌اند** — سندباکس Docker daemon ندارد (محدودیت مستند در `docs/environment-limitations.md`). صحت‌سنجی در این محیط: تست‌های رفتاری backend/frontend و امکان‌سنجی ابزار healthcheck؛ اجرای واقعی باید در CI یا ماشین شما انجام شود.
- **CI:** `.github/workflows/ci.yml` **فقط فایل است و هرگز اجرا نشده** (runner ندارد). PostgreSQL واقعی فقط به‌صورت embedded (PostgreSQL 16.2 واقعی روی سوکت، بدون mock/SQLite) در تست‌های integration همین سندباکس اجرا شده: `download/evidence/backend_integration_tests_r1.txt`.

## فایل‌های تغییر یافته (فقط مربوط به P1/P2)

`backend/app/core/config.py` · `backend/app/core/db.py` · `backend/app/main.py` · `backend/app/core/middleware.py` (docstring قرارداد) · `backend/app/api/v1/health.py` · `backend/app/core/logging.py` · `backend/tests/unit/test_config.py` · `backend/tests/unit/test_health.py` · `backend/tests/unit/test_db.py` (جدید) · `backend/tests/unit/test_request_lifecycle.py` (جدید) · `.github/workflows/ci.yml` · `frontend/vite.config.ts` · `docker-compose.yml` · `Caddyfile` · `.env.example` · `README.md` · `CHANGELOG.md` · `docs/dependencies.md` · `download/Phase2_Step1_Report.md` (عدد P2-06)

**شواهد رِ-رِان:** `download/evidence/backend_lint_type_test_r1.txt` · `backend_integration_tests_r1.txt` · `backend_smoke_r1.txt` · `frontend_gates_r1.txt`
