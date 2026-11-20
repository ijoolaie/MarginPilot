# MarginPilot

پلتفرم Mini-SaaS برای تحلیل سود واقعی کالاها، مقایسهٔ قیمت تأمین‌کنندگان و شناسایی محصولات زیان‌ده؛ با تمرکز اولیه بر فروشگاه‌ها و کسب‌وکارهای کوچک و متوسط ایران.

**وضعیت محصول:** زیرساخت، هویت/نشست، tenancy/RBAC، کاتالوگ و تأمین‌کنندگان، ورود اطلاعات کالا و قیمت تأمین‌کننده و موتور مقایسهٔ قیمت در Backend پیاده‌سازی شده‌اند. قابلیت‌های فروش/هزینه، موتور سود واقعی، رابط کاربری محصول و گزارش‌های نهایی هنوز در نقشهٔ راه باقی‌اند.

**سیاست اجرایی مصوب:** رسیدن سریع به MVP قابل عرضه، با حداقل پیچیدگی لازم. صحت مالی، جداسازی tenant، امنیت پایه، تست واقعی PostgreSQL و بازیابی backup قابل مصالحه نیستند؛ معماری توزیع‌شده و قابلیت‌های سازمانی تا اثبات نیاز به بعد موکول‌اند.

## وضعیت تحویل‌شده

| حوزه | وضعیت |
|---|---|
| زیرساخت، Docker Compose و CI | پیاده‌سازی‌شده؛ CI انتشارهای Phase 4 سبز بوده است |
| Authentication و session امن | پیاده‌سازی‌شده در Phase 3 |
| Tenancy و RBAC | پیاده‌سازی‌شده در Phase 3 |
| کالا، دسته، واریانت، تأمین‌کننده و لیست قیمت | پیاده‌سازی‌شده در Phase 4 Step 1–2 |
| Import کالا و قیمت تأمین‌کننده | پیاده‌سازی‌شده در Phase 4 Step 3؛ Sales import تا آماده‌شدن دامنهٔ فروش غیرفعال است |
| مقایسهٔ قیمت تأمین‌کنندگان | Backend/API در Phase 4 Step 4؛ UI و export نهایی هنوز باقی است |
| فروش، مرجوعی و هزینه‌ها | طراحی/قرارداد موجود؛ پیاده‌سازی اجرایی باقی است |
| محاسبهٔ سود واقعی و قیمت پیشنهادی | اصول و بردارهای مرجع طراحی شده؛ موتور اجرایی باقی است |
| داشبورد و گزارش‌های محصول | باقی است |

برای جزئیات شواهد، محدودیت‌ها و معیار پذیرش به [نقشهٔ راه MVP](docs/mvp-roadmap.md) و [برنامهٔ Phase 4](docs/phase4-plan.md) مراجعه کنید.

## نقشهٔ راه مصوب ادامهٔ پروژه

- **Phase 5 — Sales & Expenses:** فروش، اقلام، مرجوعی، هزینه‌های مستقیم/مشترک و فعال‌سازی امن Sales import.
- **Phase 6 — Financial Calculation Engine:** محاسبات deterministic و نسخه‌دار درآمد خالص، بهای تمام‌شده، سود و قیمت پیشنهادی.
- **Phase 7 — MVP UI, Dashboard & Reports:** جریان‌های اصلی UI فارسی RTL، داشبورد ضروری، مقایسهٔ قابل استفاده و خروجی Excel/PDF.
- **Phase 8 — Release Readiness:** E2E حیاتی، hardening امنیتی/کارایی متناسب با MVP، استقرار و backup/restore آزموده‌شده.

Microservices، صف پیچیده، حسابداری کامل، گزارش‌ساز سفارشی، AI مالی، اپ موبایل و مقیاس‌پذیری سازمانی جزو MVP نیستند.

## فناوری‌ها

- Backend: Python 3.12، FastAPI، Pydantic v2، SQLAlchemy 2، Alembic، psycopg3
- Database: PostgreSQL
- Frontend: React، TypeScript، Vite، Tailwind، RTL فارسی
- تست: Pytest/HTTPX، PostgreSQL integration، Vitest و CI
- فایل‌ها: Pandas، OpenPyXL و ReportLab طبق نیاز قابلیت‌ها
- پول: Decimal و PostgreSQL NUMERIC؛ محاسبات مالی در Backend

## اجرای محلی (Windows PowerShell)

### Backend

```powershell
Copy-Item .env.example .env
# مقادیر محیطی را تنظیم کنید؛ DATABASE_URL باید از postgresql+psycopg:// استفاده کند.
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.lock --require-hashes
uvicorn app.main:app --reload --port 8000
```

Health endpoints:
- `http://localhost:8000/health/live`
- `http://localhost:8000/health/ready`

### Frontend

در پنجرهٔ PowerShell جداگانه:

```powershell
cd frontend
npm ci
npm run dev
```

Vite روی پورت 3000 اجرا می‌شود و درخواست‌های `/api` را به Backend پروکسی می‌کند.

### تست‌ها

```powershell
# Backend (با venv فعال)
cd backend
pytest
ruff check app tests
mypy app

# Frontend
cd frontend
npm run lint
npm run type-check
npm test
npm run build
```

تست‌های integration باید با PostgreSQL واقعی اجرا شوند؛ SQLite یا mock جایگزین تست قیود و تراکنش‌های PostgreSQL نیست.

### Docker Compose

```powershell
Copy-Item .env.example .env
# POSTGRES_PASSWORD و سایر مقادیر را تنظیم کنید
docker compose up -d --build
docker compose ps
curl.exe http://localhost:8080/api/health/ready
curl.exe http://localhost:8080/healthz
```

برای توقف محیط همین پروژه: `docker compose down`. از `docker compose down -v` فقط وقتی استفاده کنید که حذف volume داده‌های همین پروژه عمداً مدنظر باشد.

## اسناد کلیدی

- [نقشهٔ راه مصوب Mini-SaaS MVP](docs/mvp-roadmap.md)
- [معماری](docs/architecture.md)
- [مدل داده](docs/data-model.md)
- [قرارداد API](docs/api-contract.md)
- [اصول محاسبات مالی](docs/calculation-principles.md)
- [کاتالوگ و دادهٔ تأمین‌کننده](docs/catalog-data.md)
- [موتور مقایسه](docs/comparison-engine.md)
- [برنامهٔ Phase 3](docs/phase3-plan.md) · [برنامهٔ Phase 4](docs/phase4-plan.md)
- [امنیت](docs/security.md) · [استراتژی تست](docs/testing-strategy.md) · [وابستگی‌ها](docs/dependencies.md) · [تصمیم‌ها](docs/decisions.md)
- [Changelog](CHANGELOG.md) · [Security Policy](SECURITY.md)

## قواعد انتشار

- ریپوی canonical: `ijoolaie/MarginPilot`.
- `main` و شاخه‌های انتشار فقط با مجوز صریح تغییر می‌کنند.
- هر فاز پس از تست، بازبینی و به‌روزرسانی مستندات بسته می‌شود؛ سپس فاز بعد آغاز می‌شود.
- وضعیت «تکمیل‌شده» فقط با کد اجرایی و شواهد تست/CI اعلام می‌شود؛ وجود سند طراحی به معنی پیاده‌سازی نیست.
