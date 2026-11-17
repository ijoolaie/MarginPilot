# MarginPilot — گزارش Phase 0: ممیزی Repository و محیط اجرا

**تاریخ:** ۲۰۲۶-۱۱-۱۶ (۲۵ آبان ۱۴۰۵)
**وضعیت فاز:** COMPLETED (فقط ممیزی — هیچ قابلیتی در این فاز پیاده‌سازی نشده است)
**دامنه:** دقیقاً مطابق بخش ۱۶ و ۱۹ (دستور اجرایی اول) — پس از این گزارش، شروع Phase 1 منوط به تأیید شماست.

| بند خواسته‌شده در دستور | محل پوشش در این سند |
|---|---|
| ۱. وضعیت فعلی پروژه | بخش ۱ |
| ۲. ابزارهای نصب‌شده | بخش ۲ |
| ۳. ساختار فایل‌ها | بخش ۳ |
| ۴. مشکلات موجود | بخش ۴ |
| ۵. وابستگی‌های لازم | بخش ۵ |
| ۶. ریسک‌های فنی | بخش ۶ |
| ۷. طرح معماری پیشنهادی | بخش ۷ |
| ۸. برنامه Phaseهای بعدی | بخش ۸ |
| ۹. تخمین پیچیدگی هر مرحله | بخش ۸ (ستون پیچیدگی و تلاش) |
| ۱۰. معیار پذیرش هر مرحله | بخش ۹ |

---

## ۱) وضعیت فعلی پروژه

| مورد | نتیجه بررسی واقعی |
|---|---|
| مسیر Repository | `/home/z/my-project` (شاخه `main`) |
| وضعیت Git | Working tree پاک؛ فقط یک commit: `0a48216 Initial commit` |
| فایل‌های Tracked | `.env` ، `.gitignore` ، `download/README.md` — هیچ‌کدام کد یا مستند MarginPilot نیستند |
| کد MarginPilot | **صفر** — هیچ `package.json` / `pyproject.toml` / `requirements.txt` / `Dockerfile` / `docker-compose.yml` / `alembic.ini` / `vite.config` در ریپو وجود ندارد |
| سرویس‌های در حال اجرا | فقط زیرساخت خود سندباکس (Caddy معکوس‌پروکسی سندباکس، فرایند driver) — هیچ سرویسی از MarginPilot در حال اجرا نیست |
| امکانات پیاده‌سازی‌شده | هیچ (۰٪) |
| امکانات فقط مستندشده | تمام ماژول‌های بخش ۶ Master Prompt — صرفاً در حد سند، بدون هیچ پیاده‌سازی |

**تفکیک پیاده‌سازی‌شده از مستندشده:** همهٔ قابلیت‌های تعریف‌شده در Master Prompt فقط «مستندشده» هستند و هیچ‌کدام «پیاده‌سازی‌شده» نیستند. جدول وضعیت هر ماژول در بخش ۱۰ آمده است. چون ریپو عملاً خالی است، طبق دستور («اگر Repository خالی است، ساختار را ایجاد کن») پیشنهاد ساختار کامل در بخش ۷ ارائه شده است.

---

## ۲) ابزارهای نصب‌شده

| ابزار / منبع | وضعیت | نسخه / جزئیات (استعلام واقعی) |
|---|---|---|
| سیستم‌عامل | موجود | Debian 13 (trixie)، x86_64 |
| Python | ✅ موجود | 3.12.16 (venv فعال: `/home/z/.venv`) |
| pip | ✅ موجود | 26.3 |
| uv | ✅ موجود | مدیریت وابستگی سریع (گزینه پیشنهادی برای lock) |
| Node.js | ✅ موجود | v24.22.3 |
| npm | ✅ موجود | 11.19.1 |
| git | ✅ موجود | 2.47.3 |
| make / curl | ✅ موجود | 4.4.1 / 8.14.1 |
| gcc / g++ | ✅ موجود | برای کامپایل درایور در صورت نیاز (`pg_config` هم موجود است) |
| **Docker / Docker Compose** | ❌ **غایب** | نه CLI و نه daemon؛ بدون دسترسی root قابل نصب نیست |
| **PostgreSQL** | ❌ **غایب** | هیچ باینری سرور/کلاینت (`psql`، `pg_ctl`) نصب نیست |
| **Redis** | ❌ **غایب** | فقط کلاینت Python + `fakeredis` (برای تست کافی است) |
| sudo / root | ❌ ندارد | uid=1001(z)؛ نصب سرویس سیستمی ممکن نیست |
| Playwright (Python) | ✅ موجود | 1.57.0 + Chromium (revision 1200) در کش مرورگر |
| منابع سخت‌افزاری | — | 2 vCPU ، 4.1 GB RAM ، حدود 8 GB دیسک آزاد |
| شبکه | ✅ باز | PyPI، npm registry و GitHub همه HTTP 200 پاسخ دادند |

**پکیج‌های Python مرتبط که از قبل در venv نصب‌اند:** fastapi 0.128.0، uvicorn 0.44.0، pydantic 2.12.5 + pydantic-settings 2.13.1، python-multipart، argon2-cffi 25.1.0 (Argon2id ✔)، pandas 2.2.3، openpyxl 3.1.5، xlsxwriter 3.2.9، reportlab 4.4.9، httpx 0.28.1، pytest 9.0.2 (+ asyncio و cov)، redis-py 7.4.0، fakeredis 2.34.1، ماژول `jwt` (PyJWT).

**غایب‌های حیاتی Backend (با import-check تأیید شد):** `sqlalchemy`، `alembic`، `psycopg` — همچنین `polars`، `ruff` و `mypy` نصب نیستند. همه از PyPI قابل نصب‌اند (شبکه باز است و دانلود آزمایشی `fastapi` با موفقیت انجام شد).

**هشدار نسخه:** پکیج‌های global سندباکس (مثلاً fastapi 0.128.0) با آخرین نسخهٔ registry (0.163.1) تفاوت دارند. پروژه باید venv و lock file مستقل خودش را داشته باشد تا نسخه‌ها دقیقاً pin و build قابل تکرار باشد؛ وابستگی به پکیج‌های از پیش نصب سندباکس نخواهیم داشت.

---

## ۳) ساختار فایل‌ها (وضعیت موجود)

```
/home/z/my-project
├── .env                  # tracked در Git ⚠️ — یک خط: DATABASE_URL=file:/home/z/my-project/db/custom.db
├── .gitignore            # فقط دو خط: skills/ و node_modules/ (ناکافی برای پروژه واقعی)
├── download/             # محل تحویل خروجی‌ها به کاربر (زیرساخت سندباکس)
│   └── README.md
├── skills/               # مهارت‌های از پیش نصب‌شدهٔ سندباکس (غیرمرتبط با MarginPilot — ignored)
├── upload/               # خالی — هنوز هیچ فایلی (مثلاً فایل فروش نمونه) آپلود نشده است
└── .git/
```

نتیجه: هیچ شاخهٔ backend/، frontend/، docs/، tests/ یا فایل پیکربندی پروژه وجود ندارد؛ پروژه از صفر شروع می‌شود.

---

## ۴) مشکلات موجود

1. **`.env` در Git ردیابی شده** ⚠️ (شدت: کم) — محتوای فعلی بی‌خطر است (فقط `DATABASE_URL` پیش‌فرض سندباکس، بدون هیچ Secret)، اما این الگو برای پروژه‌ای که باید Secrets را مدیریت کند خطرناک است. اصلاح در Phase 2: `git rm --cached .env`، `.gitignore` کامل و معرفی `.env.example`.
2. **`.gitignore` ناکافی است** — باید شامل `.env`، `__pycache__/`، `.venv/`، `dist/`، `coverage/`، فایل‌های موقت import و خروجی‌های build شود.
3. **Docker غایب است** — معیار پذیرش نهایی شمارهٔ ۱ («اجرا با Docker Compose») در همین سندباکس قابل راستی‌آزمایی نیست. فایل‌ها به‌طور کامل نوشته و در CI واقعاً build می‌شوند، اما اجرای نهایی باید روی سیستم شما یا GitHub Actions انجام شود (راهکار: بخش ۶، R1).
4. **PostgreSQL و Redis غایب‌اند** — تست Integration واقعی روی Postgres در سندباکس ممکن نیست؛ دو مسیر جایگزین در بخش ۶ (R2) پیشنهاد شده است.
5. **مسیر `DATABASE_URL` در `.env` به شاخه‌ای ناموجود اشاره می‌کند** (`db/custom.db`) — این فایل پیش‌فرض سندباکس است و با پیکربندی واقعی پروژه جایگزین می‌شود.
6. **تفاوت نسخهٔ پکیج‌های global با نسخه‌هایی که pin خواهیم کرد** — بدون lock file، تکرارپذیری build تضمین نمی‌شود.
7. **نسخه‌های بسیار جدید اکوسیستم Frontend** (TypeScript 7.0.2، Vite 8.3.8، Zod 4.6.7) — قبل از pin، ماتریس سازگاری (مثلاً سازگاری `@hookform/resolvers` با Zod 4) بررسی می‌شود؛ در صورت تداخل، آخرین نسخهٔ پایدارِ سازگار انتخاب و در `CHANGELOG.md` ثبت می‌گردد.

---

## ۵) وابستگی‌های لازم

نسخه‌ها **در همین روز از registry رسمی استعلام شده‌اند** (نه حدس و نه حافظه). در Phase 2 دقیقاً pin و در lock file قفل می‌شوند.

### Backend (PyPI)

| بسته | آخرین نسخهٔ استعلام‌شده | نقش | وضعیت در سندباکس |
|---|---|---|---|
| fastapi | 0.163.1 | فریم‌ورک API | نصب (0.128.0) — ارتقا با lock |
| uvicorn | 0.54.0 | سرور ASGI | نصب (0.44.0) |
| pydantic / pydantic-settings | 2.12.5 / 2.13.1 | اعتبارسنجی / پیکربندی | نصب ✅ |
| sqlalchemy | 2.1.8 | ORM | ❌ باید نصب شود |
| alembic | 1.20.1 | Migration | ❌ باید نصب شود |
| psycopg (3) | 3.3.9 | درایور PostgreSQL | ❌ باید نصب شود |
| argon2-cffi | 25.1.0 | هش رمز با Argon2id | نصب ✅ |
| PyJWT | 2.15.1 | فقط امضای توکن موقت (لینک بازیابی رمز) | نصب (ماژول `jwt` موجود) |
| pandas | 2.2.3 | پردازش CSV/XLSX | نصب ✅ (جایگزین: polars 2.1.0 — تصمیم در بخش ۱۲) |
| openpyxl / xlsxwriter | 3.1.5 / 3.2.9 | خواندن / تولید XLSX | نصب ✅ |
| reportlab + arabic-reshaper + python-bidi | 4.4.9 / — / — | تولید PDF فارسی RTL | reportlab نصب؛ دو بستهٔ دیگر نصب می‌شوند |
| httpx | 0.28.1 | تست API | نصب ✅ |
| pytest (+asyncio، +cov) | 9.0.2 | تست | نصب ✅ |
| ruff / mypy | 0.17.5 / 2.4.1 | Lint / Type-check | ❌ باید نصب شوند |

### Frontend (npm)

| بسته | آخرین نسخهٔ استعلام‌شده | نقش |
|---|---|---|
| react / react-dom | 19.3.1 | رابط کاربری |
| vite | 8.3.8 | ابزار build |
| typescript | 7.0.2 ⚠️ | پس از بررسی سازگاری، در صورت نیاز آخرین 5.x/6.x انتخاب می‌شود |
| tailwindcss | 4.3.5 | استایل (RTL با logical properties) |
| @tanstack/react-query | 5.107.1 | مدیریت state سمت سرور |
| react-hook-form + @hookform/resolvers | 7.92.0 / (استعلام در Phase 2) | فرم‌ها |
| zod | 4.6.7 | Schema validation |
| echarts | 6.1.0 | نمودارها |
| vitest | 5.1.0 | تست واحد Frontend |
| @playwright/test | 1.65.1 | تست E2E |
| react-router / vazirmatn (فونت) | (استعلام در Phase 2) | Routing / فونت فارسی UI |

### Infrastructure

- Imageها: `postgres:16-alpine`، `caddy:2` (یا nginx) — تگ دقیق در Phase 2 pin می‌شود.
- GitHub Actions: lint، type-check، تست‌های unit/integration، build دو سرویس، اسکن وابستگی (pip-audit / npm audit) و اسکن Secret (gitleaks).

---

## ۶) ریسک‌های فنی

| # | ریسک | شدت | راهکار کاهش |
|---|---|---|---|
| R1 | Docker در سندباکس در دسترس نیست → اجرای compose و AC#1 اینجا قابل آزمایش نیست | **بالا** | فایل‌های Docker و workflow کامل CI ساخته و در GitHub Actions واقعاً build/اجرا می‌شوند؛ اجرای محلی نهایی روی سیستم شما مستند می‌شود. در صورت فعال‌شدن Docker در سندباکس، آزمایش محلی هم انجام خواهد شد |
| R2 | PostgreSQL محلی وجود ندارد → تست‌های Integration/Migration | **بالا** | (الف) اجرای integration tests در CI با سرویس‌کانتینر postgres (پیشنهاد اصلی)؛ (ب) آزمایش باینری embedded-postgres بدون root در Phase 3. منطق مالی از DB جدا و با Unit test مستقل پوشش داده می‌شود |
| R3 | صحت محاسبات مالی و قوانین گرد کردن (تومان/ریال بدون واحد خرد) | **بالا** | فقط `Decimal`، قانون گرد صریح و مستند، ثبت `formula_version` + ورودی/خروجی هر محاسبه، قابلیت بازتولید گزارش |
| R4 | رندر فارسی/RTL در PDF | متوسط | پروتوتایپ PDF فارسی در ابتدای Phase 11 با فونت وزیرمتن + reshaping؛ در صورت شکست، مسیر جایگزین (HTML→PDF) بررسی می‌شود |
| R5 | محدودیت منابع سندباکس (2CPU / 4GB RAM / ~8GB دیسک) | متوسط | تست Performance سبک در سندباکس؛ اعداد واقعی و بار هم‌زمان در CI یا سیستم شما |
| R6 | ناسازگاری نسخه‌های خیلی جدید (TS7، Vite8، Zod4) | متوسط | بررسی ماتریس سازگاری قبل از pin؛ انتخاب محافظه‌کارانه و ثبت در CHANGELOG |
| R7 | امنیت فایل آپلود (XLSX/CSV مخرب، zip bomb، ماکرو) | متوسط | محدودیت حجم/نوع، بررسی magic bytes، رد `xlsm` و محتوای فعال، openpyxl فقط در حالت `read_only` + `data_only`، نگهداری موقت با نام امن و حذف خودکار پس از پردازش |
| R8 | ابطال نشست بدون Redis | کم | جدول `sessions` در PostgreSQL (قابل ابطال فوری پس از خروج/تغییر رمز)؛ Redis فقط در صورت اثبات نیاز اضافه می‌شود |

---

## ۷) طرح معماری پیشنهادی

**الگو:** Modular Monolith تک‌ریپویی (monorepo) — بدون Microservices در v1.

```
marginpilot/  (ریپوی اصلی)
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── core/            # config، db session، security، middleware، error schema، money (Decimal)
│   │   ├── modules/
│   │   │   ├── identity/    # auth، users، sessions، rbac
│   │   │   ├── tenancy/     # tenants، memberships، tenant context
│   │   │   ├── catalog/     # products، product_variants، suppliers، supplier_prices
│   │   │   ├── sales/       # orders، sale_items، returns، وضعیت‌ها
│   │   │   ├── expenses/    # انواع هزینه + تخصیص
│   │   │   ├── imports/     # state machine موتور ورود داده (CSV/XLSX)
│   │   │   ├── pricing/     # موتور محاسبه (توابع خالص دامنه) + قیمت پیشنهادی
│   │   │   ├── comparison/  # مقایسه لیست قیمت تأمین‌کنندگان
│   │   │   ├── analytics/
│   │   │   ├── reporting/   # PDF/XLSX/CSV
│   │   │   ├── billing/     # فقط اسکلت قابل توسعه با Adapter درگاه
│   │   │   └── audit/       # audit_logs
│   │   └── api/v1/          # routerها + schemaهای Pydantic (پیشوند /api/v1)
│   ├── tests/               # unit / integration / security
│   ├── alembic/
│   ├── pyproject.toml + lock file
│   └── Dockerfile
├── frontend/
│   ├── src/                 # features/ ، components/ ، lib/ ، routes/ — فارسی RTL
│   ├── tests/ (vitest) + e2e/ (playwright)
│   └── Dockerfile (سرو static با nginx/caddy)
├── docker-compose.yml       # frontend، backend، postgres، reverse-proxy
├── .github/workflows/ci.yml
├── docs/                    # معماری، API، امنیت، قوانین محاسبات، نصب، بکاپ، عیب‌یابی
├── .env.example             # بدون هیچ Secret واقعی
└── README.md / SECURITY.md / CHANGELOG.md
```

**تصمیم‌های معماری کلیدی (نیازمند تأیید — بخش ۱۲):**

1. **احراز هویت: Session opaque token در Cookie** (`httpOnly`، `Secure`، `SameSite=Lax`) + جدول `sessions` در PostgreSQL. دلایل: ابطال فوری پس از خروج/تغییر رمز، مقاومت بهتر نسبت به JWT ذخیره‌شده در localStorage در برابر XSS، سادگی در استقرار same-origin پشت reverse proxy. JWT فقط برای لینک موقت بازیابی رمز. CSRF با SameSite + توکن double-submit برای درخواست‌های mutate. Brute-force با rate limit per-IP/per-user روی `/auth/login` و قفل تدریجی.
2. **Tenant isolation:** کاربر پس از ورود، tenant فعال را بین membershipهای خود انتخاب می‌کند؛ middleware هر درخواست را به `TenantContext` تبدیل می‌کند و تمام کوئری‌های دامنه در لایهٔ Repository به‌صورت اجباری با `tenant_id` اسکوپ می‌شوند + تست IDOR اختصاصی بین tenantها.
3. **پول:** همهٔ محاسبات با `Decimal`؛ ذخیرهٔ `NUMERIC(20,2)` برای مبالغ و `NUMERIC(12,6)` برای نرخ‌ها/حاشیه؛ واحد پول در سطح tenant (تومان یا ریال)؛ **هیچ تبدیل ضمنی انجام نمی‌شود**.
4. **موتور محاسبه:** توابع خالص (pure) مستقل از DB و Framework؛ ورودی/خروجی هر محاسبه با `formula_version` در جدول `calculations` ثبت می‌شود تا هر گزارش قابل بازتولید باشد؛ گزارش‌ها فقط از همین توابع تغذیه می‌شوند.
5. **Import engine:** state machine با مراحل upload → parse → map → validate → awaiting_confirmation → committed/failed؛ ردیف‌های خطادار با دلیل در `import_rows`؛ فایل خام فقط موقت با hash و حذف خودکار.
6. **RBAC:** جدول‌های `roles`/`permissions` با نقش‌های Owner، Admin، Analyst، Viewer، System Admin؛ اعمال واقعی سمت Backend با dependency injection در FastAPI؛ Frontend فقط نمایش را تطبیق می‌دهد.
7. **Rate limiting نسخهٔ اول:** middleware درون‌حافظه‌ای (per-IP / per-user) با آماده‌سازی برای انتقال به Redis؛ تست‌ها با `fakeredis`/mock.
8. **Idempotency Key** برای عملیات حساس (ثبت import، تولید گزارش) با کلید یکتا و ذخیرهٔ نتیجه.

---

## ۸) برنامه فازهای بعدی + تخمین پیچیدگی

| Phase | محدوده | پیچیدگی | تلاش نسبی* | وابستگی محیطی |
|---|---|---|---|---|
| 1 | اسکلت معماری، پیکربندی، لاگ ساختاری، اسکلت تست | کم | S (۲–۳ نفرروز) | — |
| 2 | Docker، compose، Caddy، CI پایه، `.env.example`، مایگریشن پایه | متوسط | M (۳–۴) | اجرای compose فقط خارج سندباکس ⚠️ |
| 3 | احراز هویت + Multi-tenancy + نشست‌ها | بالا | L (۵–۷) | Postgres در CI |
| 4 | RBAC و مدیریت کاربران/عضویت‌ها | متوسط | M (۳–۴) | — |
| 5 | محصولات و تأمین‌کنندگان + تاریخچه قیمت | متوسط | M (۳–۵) | — |
| 6 | موتور Import (CSV/XLSX، mapping، preview، اعتبارسنجی) | بالا | L (۵–۸) | — |
| 7 | فروش‌ها و هزینه‌ها + تخصیص هزینه مشترک | متوسط–بالا | M/L (۴–۶) | — |
| 8 | موتور محاسبه سود + قیمت پیشنهادی (قلب محصول) | **خیلی بالا** | L/XL (۵–۸) | — |
| 9 | مقایسه قیمت تأمین‌کنندگان + خروجی Excel | متوسط–بالا | M/L (۴–۶) | — |
| 10 | Analytics و داشبورد | متوسط | M (۳–۵) | — |
| 11 | Report engine (PDF فارسی، XLSX، CSV) | متوسط | M (۳–۵) | پروتوتایپ PDF فارسی |
| 12 | سخت‌سازی امنیتی (headers، rate limit، audit، اسکن) | متوسط | M (۳–۴) | — |
| 13 | E2E و Performance | متوسط–بالا | M/L (۴–۶) | مرورگر Chromium در سندباکس موجود؛ بار واقعی خارج |
| 14 | استقرار و مستندات نهایی + Backup/Restore | کم–متوسط | S/M (۲–۳) | اجرای compose خارج سندباکس |

\* اعداد نفرروز **تخمین تقریبی برای برنامه‌ریزی** هستند، نه تعهد دقیق. جمع تقریبی MVP: حدود **۴۵ تا ۶۵ نفرروز**.

ترتیب اجرا همان ترتیب Master Prompt است و هر Phase پس از گزارش نتایج و تأیید شما آغاز می‌شود.

---

## ۹) معیار پذیرش هر فاز

| Phase | معیار پذیرش (همه باید برقرار باشند) |
|---|---|
| 1 | ساختار ماژولار بدون import دایره‌ای؛ config فقط از متغیرهای محیطی؛ لاگ ساختاری با `request_id`؛ تست دود سبز |
| 2 | `docker compose up` چهار سرویس را بالا می‌آورد؛ healthcheckها سبز؛ Alembic از صفر اجرا می‌شود؛ CI روی PR همهٔ مراحل بخش ۱۳ را اجرا می‌کند؛ هیچ Secret در ریپو نیست |
| 3 | ثبت‌نام/ورود/خروج/تغییر رمز کار می‌کند؛ Argon2id؛ نشست پس از خروج/تغییر رمز قابل ابطال است؛ rate limit روی login فعال است؛ **تست IDOR بین tenantها سبز است**؛ migrationها اجرا و بازگشت‌پذیر (downgrade) هستند |
| 4 | نقش‌ها واقعاً سمت Backend اعمال می‌شوند؛ تلاش برای Privilege Escalation (مثلاً Viewer → API مدیریتی) با 403 شکست می‌خورد |
| 5 | CRUD با اعتبارسنجی؛ SKU یکتا در محدودهٔ tenant؛ soft delete؛ تاریخچهٔ قیمت تأمین‌کننده ثبت می‌شود |
| 6 | CSV/XLSX واقعی parse می‌شود؛ فایل مخرب/خراب/حجیم/غلط رد می‌شود با پیام فارسی؛ mapping + preview + تأیید دو مرحله‌ای؛ گزارش خطا قابل دانلود است |
| 7 | سفارش/قلم/تخفیف/مرجوعی/وضعیت‌ها ثبت می‌شوند؛ تخصیص هزینه شفاف و قابل بازبینی است؛ سفارش لغوشده در درآمد حساب نمی‌شود (تست دارد) |
| 8 | تمام فرمول‌های بخش ۶.۱۰ با Unit test پوشش داده شده‌اند (تخفیف دوبل، تقسیم بر صفر، اعداد منفی، مرجوعی، گرد کردن، هزینهٔ تکراری)؛ `formula_version` و بازتولید گزارش تست شده است |
| 9 | مقایسهٔ دو لیست با تطبیق SKU/نام نرمال‌شده؛ موارد نامطمئن فقط «پیشنهاد» برای تأیید کاربرند؛ محاسبهٔ اثر تغییر قیمت خرید بر سود؛ خروجی Excel |
| 10 | داشبورد فقط از موتور محاسبه تغذیه می‌شود؛ فیلترها (زمان/محصول/دسته/تأمین‌کننده/وضعیت) کار می‌کنند؛ صحت اعداد با تست عددی تأیید می‌شود |
| 11 | PDF فارسی سالم + XLSX + CSV تولید می‌شود؛ هر گزارش شامل متادیتای الزامی بخش ۶.۱۲ (تاریخ، tenant، بازه، فیلترها، واحد پول، روش محاسبه، هشدار کیفیت داده) است |
| 12 | Headers امن؛ تست brute-force سبز؛ audit log ثبت می‌شود؛ اسکن وابستگی و Secret در CI بدون یافتهٔ بحرانی |
| 13 | سناریوی E2E ده‌مرحله‌ای بخش ۱۱ سبز است؛ تست Performance پایه روی فایل‌های کوچک/متوسط/بزرگِ مجاز انجام شده است |
| 14 | README/SECURITY/CHANGELOG کامل؛ Backup و Restore یک‌بار واقعاً اجرا و مستند شده است |

---

## ۱۰) جدول وضعیت قابلیت‌ها

همهٔ ماژول‌های محصول در وضعیت **NOT STARTED** هستند:

| ماژول | وضعیت |
|---|---|
| Authentication | NOT STARTED |
| Multi-Tenancy | NOT STARTED |
| User & Role Management | NOT STARTED |
| Product Management | NOT STARTED |
| Supplier Management | NOT STARTED |
| Sales Management | NOT STARTED |
| Expense Management | NOT STARTED |
| Import Engine | NOT STARTED |
| Supplier Price Comparison | NOT STARTED |
| Calculation Engine | NOT STARTED |
| Analytics Engine | NOT STARTED |
| Report Engine | NOT STARTED |
| Billing (اسکلت) | NOT STARTED |
| Frontend (۱۳ صفحه) | NOT STARTED |
| Docker / CI / مستندات | NOT STARTED (فقط ممیزی این فاز انجام شد) |

---

## ۱۱) گزارش پیشرفت به فرمت استاندارد (بخش ۱۸)

- **Phase:** 0 — Repository and Environment Audit
- **Status:** COMPLETED (فقط ممیزی؛ هیچ قابلیتی پیاده‌سازی نشده است)
- **Completed Tasks:** ممیزی کامل Git، فایل‌ها، ابزارها، سرویس‌های در حال اجرا، شبکه و منابع؛ بررسی import پکیج‌های حیاتی؛ استعلام نسخهٔ وابستگی‌ها از PyPI و npm؛ شناسایی مشکلات و ۸ ریسک فنی با راهکار؛ تدوین معماری پیشنهادی، برنامهٔ فازها، تخمین پیچیدگی و معیارهای پذیرش
- **Created Files:** `download/Phase0_Environment_Audit_Report.md` (همین سند)
- **Modified Files:** هیچ — هیچ فایلی از Repository تغییر نکرده و commit جدیدی انجام نشده است
- **Tests Executed (محیطی، نه محصولی):** reachability سه registry (PyPI/npm/GitHub → هر سه HTTP 200)؛ دانلود آزمایشی `fastapi` از PyPI (موفق)؛ import-check ماژول‌های `sqlalchemy`/`alembic`/`psycopg`/`polars` (هر چهار MISSING — یافتهٔ محیطی است، نه شکست تست)
- **Tests Passed:** همهٔ پروب‌های محیطی فوق
- **Tests Failed:** هیچ (تست محصولی در این فاز وجود ندارد)
- **Security Findings:** یک یافته با شدت کم — فایل `.env` در Git tracked است (بدون Secret واقعی؛ نقص بهداشتی ریپو). هیچ رمز، توکن یا Secret دیگری در ریپو یافت نشد. سرویس‌های اجراشده فقط زیرساخت سندباکس‌اند و سطح حملهٔ جدیدی ایجاد نمی‌کنند
- **Known Limitations:** بدون Docker/PostgreSQL/Redis و بدون sudo؛ اجرای compose و integration روی Postgres فقط در CI یا سیستم شما؛ منابع سندباکس محدود (2CPU/4GB)؛ نسخه‌های برخی بسته‌ها (@hookform/resolvers، react-router، فونت) در Phase 2 استعلام می‌شود
- **Acceptance Criteria (این فاز):** ارائهٔ گزارش دقیق ممیزی با تمام ۱۰ بند خواسته‌شده ✅ — همین سند
- **Evidence:** همهٔ اعداد و نسخه‌ها از استعلام زندهٔ دستورات در همین جلسه است (نسخهٔ ابزارها با `--version`، نسخهٔ بسته‌ها با `pip index versions` و `npm view`، دسترسی شبکه با curl) — نه از حافظه و نه حدس
- **Next Phase:** Phase 1 — Architecture and Project Structure (**در انتظار تأیید شما**)

---

## ۱۲) تصمیم‌های نیازمند تأیید شما

1. **استراتژی تست Integration:** پیشنهاد من CI-first (GitHub Actions با سرویس‌کانتینر Postgres) است؛ گزینهٔ دوم، باینری embedded-postgres بدون root در سندباکس (در Phase 3 آزمایش می‌شود).
2. **پردازش داده:** پیشنهاد **pandas** برای v1 (نصب و پایدار، کافی برای CSV/XLSX)؛ polars بعداً در صورت نیاز عملکردی.
3. **قانون گرد کردن پیش‌فرض:** گرد به نزدیک‌ترین واحد پول با نیم به بالا (half-up)، صریح در کد و مستند در `formula_version`.
4. **روش احراز هویت:** Session opaque در Cookie (بخش ۷، بند ۱) — در صورت ترجیح JWT یا روش دیگر، اعلام کنید.
5. **زبان‌ها:** کد و identifierها انگلیسی، UI فارسی RTL، مستندات فارسی (README فنی دوزبانه) — در صورت ترجیح دیگر بفرمایید.
6. **نسخه‌های Frontend:** TypeScript 7 و Zod 4 بسیار جدیدند؛ پیشنهاد: پینِ محافظه‌کارانه پس از چک سازگاری (احتمال انتخاب آخرین 5.x برای TS).

