# MarginPilot

پلتفرم تحلیل سود واقعی کالاها، مدیریت قیمت خرید تأمین‌کنندگان و شناسایی محصولات زیان‌ده — برای فروشگاه‌های اینترنتی، فروشندگان WooCommerce، عمده‌فروشان و کسب‌وکارهای کوچک و متوسط ایران.

**وضعیت:** Phase 1 (طراحی) تأیید شد · **Phase 2 / Step 1 (زیرساخت پایه + سازگاری وابستگی‌ها) اجرا شد** — هنوز هیچ قابلیت تجاری وجود ندارد: بدون Auth/Tenant/مدل دامنه/migration/محاسبات.

## چه چیزی در Phase 2 / Step 1 واقعاً هست

| بخش | محتوا | وضعیت اجرا در سندباکس |
|---|---|---|
| Backend | FastAPI + تنظیمات fail-fast + SQLAlchemy 2 engine + لاگ JSON + Request-ID + Error Schema + `/health/live` و `/health/ready` (`SELECT 1` واقعی) | ✅ ۳۶ unit test + ۳ integration با PostgreSQL 16.2 واقعی + smoke با uvicorn (شواهد: `download/evidence/*_r1.txt`) |
| Frontend | React 19 + TS + Vite 8 + Tailwind 4 + RTL فارسی + Vazirmatn self-host؛ صفحهٔ وضعیت Backend | ✅ lint/type-check/۳ تست/build/preview |
| Docker | Dockerfileهای non-root، docker-compose (۴ سرویس، healthcheck واقعی)، Caddyfile | ⚠️ فایل‌ها آماده؛ **اجرا نشده** (سندباکس daemon ندارد) — تست در CI/محلی شما |
| CI | `.github/workflows/ci.yml` — ۱۶ گیت + PostgreSQL واقعی | ⚠️ فقط فایل — **اجرا نشده** |
| وابستگی‌ها | exact pin + lock با hash + ماتریس سازگاری اجراشده + دو CVE برطرف | ✅ |

## اجرای محلی (Windows PowerShell)

### الف) بدون Docker — توسعهٔ روزمره

```powershell
# 0) یک‌بار: کلون و متغیرهای محیطی
git clone <repo-url> ; cd MarginPilot
Copy-Item .env.example .env
notepad .env   # مقادیر واقعی (خصوصاً DATABASE_URL) را بگذارید
#   نکته: .env باید در «ریشهٔ پروژه» باشد؛ backend حتی وقتی از پوشهٔ
#   backend/ اجرا می‌شود آن را می‌خواند (مسیر نسبت به ریشهٔ پروژه، نه CWD).
#   Environment Variables همیشه بر مقادیر فایل اولویت دارند.

# 1) Backend — Python 3.12 لازم است
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.lock --require-hashes
uvicorn app.main:app --reload --port 8000
#   تست: http://localhost:8000/health/live  و  /health/ready

# 2) Frontend — Node 24 لازم است (پنجرهٔ PowerShell جدید)
cd frontend
npm ci
npm run dev
#   http://localhost:3000  — پورت ثابت است (strictPort در vite.config.ts):
#   اگر 3000 اشغال باشد Vite با خطا متوقف می‌شود، بی‌صدا پورت عوض نمی‌کند.
#   پروکسی /api به 8000 خودکار است.

# 3) تست‌ها
# backend (پنجرهٔ فعال با venv):
cd backend ; pytest ; ruff check app tests ; mypy app
# integration با PostgreSQL واقعی خودتان:
$env:DATABASE_URL="postgresql+psycopg://marginpilot:<پسورد>@localhost:5432/marginpilot"
pytest -m integration
# frontend:
cd frontend ; npm run lint ; npm run type-check ; npm test ; npm run build
```

### ب) با Docker Compose — شبیه‌سازی کامل استقرار

```powershell
Copy-Item .env.example .env ; notepad .env   # POSTGRES_PASSWORD را واقعی کنید
docker compose up -d --build
docker compose ps          # هر ۴ سرویس (postgres/backend/frontend/caddy) باید healthy شوند
curl.exe http://localhost:8080/api/health/ready   # {"status":"ready",...}
curl.exe http://localhost:8080/healthz            # healthcheck خود Caddy
# توقف: docker compose down   |  پاک‌سازی volume: docker compose down -v
```

**قاعدهٔ رمز URL-safe (P2-04):** متغیرهای `POSTGRES_USER/PASSWORD/DB` مستقیماً در ساخت `DATABASE_URL` داخل Compose درج می‌شوند؛ پس فقط حروف، ارقام و `-_.~` مجاز است (کاراکترهایی مثل `@ : / ? # % & = + فاصله` آدرس را خراب می‌کنند). تولید رمز امن ۱۹۲-بیتی:

```powershell
$b=[byte[]]::new(24); [Security.Cryptography.RandomNumberGenerator]::Fill($b); ($b|%{$_.ToString('x2')}) -join ''
# bash:  openssl rand -hex 24
```

> توجه: پورت‌های منتشرشده فقط `8080` (Caddy) است؛ PostgreSQL و Backend از بیرون ماشین در دسترس نیستند — عمدی و طبق SECURITY.md.

## ساختار پروژه

```
backend/   app/core (config,db,logging,errors,middleware) · app/api/v1/health · tests/{unit,integration}
frontend/  src/features/welcome · src/lib/api.ts · src/App.tsx · src/main.tsx
docs/      ۱۱ سند طراحی تأییدشدهٔ Phase 1 (معماری، مدل داده، API، امنیت، …)
.github/   workflows/ci.yml
```

## سندهای طراحی (تأییدشدهٔ Phase 1)

[معماری](docs/architecture.md) · [مدل داده](docs/data-model.md) · [قرارداد API](docs/api-contract.md) · [امنیت](docs/security.md) · [اصول محاسبات](docs/calculation-principles.md) · [استراتژی تست](docs/testing-strategy.md) · [تصمیم‌ها](docs/decisions.md) · [وابستگی‌ها](docs/dependencies.md) · [محدودیت محیط](docs/environment-limitations.md) · [SECURITY](SECURITY.md) · [CHANGELOG](CHANGELOG.md)

## نقشهٔ راه

Phase 0 (ممیزی) ✅ → Phase 1 (معماری + ۵ دور بازبینی) ✅ → **Phase 2 / Step 1 (زیرساخت) ✅ در انتظار بازبینی مستقل** → Phase 2 / Step 2+ → Phase 3 (Auth/Tenant/migration) → …
