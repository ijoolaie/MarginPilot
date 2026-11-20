# محدودیت‌های محیط سندباکس و نقشهٔ اجرا (مطابق اصلاحیه B)

**وضعیت (به‌روزرسانی Phase 2 / Step 1):** حقایق §۱ دوباره اندازه‌گیری شد و نتایج اجرای واقعی Step 1 اضافه شد.

## ۱) حقایق اندازه‌گیری‌شده (Phase 0 + بازآزمایی Phase 2)

| مورد | وضعیت |
|---|---|
| OS / منابع | Debian 13 · 2 vCPU · 4.1 GB RAM · ~8 GB دیسک آزاد |
| Python / Node | 3.12.16 / v24.22.3 (npm 11.19.1) |
| **Docker** | ❌ نصب نیست (نه CLI نه daemon) و بدون sudo قابل نصب نیست — **تأیید مجدد در Phase 2** |
| **PostgreSQL سرور/کلاینت** | ❌ نصب نیست — اما **PostgreSQL 16.2 واقعی** با باینری‌های embedded بدون root (`pgserver` — ابزار تأیید صرف، وابستگی محصول نیست) اجرا و تست شد: `SELECT version()` واقعی + readiness موفق/شکست |
| Redis | ❌ نصب نیست (fakeredis برای تست کلاینت موجود است) |
| sudo/root | ❌ ندارد |
| شبکه | ✅ PyPI، npm، GitHub، Docker Registry (تأیید تگ imageها از طریق Registry HTTP API) باز |
| پایداری فرایندها | فرایندها بین پیام‌ها باقی نمی‌مانند؛ فقط فایل‌ها حفظ می‌شوند |
| **ناهنجاری ثبت‌شده** | منبع env پیش‌فرض pydantic-settings در این سندباکس مقدار برنمی‌گرداند (همهٔ نسخه‌ها آزمایش شد — شواهد: evidence/pydantic_settings_repro.txt) → بارگذاری env صریح انجام می‌شود؛ در CI بازآزمایی می‌شود |

## ۲) نتیجهٔ عملی: چه چیزی کجا اجرا می‌شود

| فعالیت | سندباکس | CI (GitHub Actions) | سیستم محلی شما |
|---|---|---|---|
| نوشتن/ویرایش کد و migrationها | ✅ | — | ✅ |
| Unit tests | ✅ (۲۱ passed) | ✅ | ✅ |
| Integration با PostgreSQL واقعی | ✅ **جدید** — با embedded PG 16.2 (بدون root) | ✅ (سرویس postgres) | ✅ (compose) |
| `docker compose up` و healthcheck | ❌ (بدون daemon — فایل‌ها ساخته و تگ‌ها/digestها راستی‌آزمایی شدند؛ **اجرای واقعی compose انجام نشده**) | ✅ (build فقط) | ✅ — **الزامی معیار پذیرش** |
| E2E با Playwright | محدود (مرورگر Chromium موجود) | ✅ | ✅ |
| Performance واقعی | ❌ (منابع محدود) | پایه | ✅ (عدد نهایی) |

**تعهد طبق شرط Integration Testing:** تست‌های integration فقط با PostgreSQL واقعی معتبر شمرده می‌شوند؛ mock جایگزین نیست. در Step 1 این با embedded PG 16.2 در سندباکس (بخش‌های ready موفق/شکست) و طراحی سرویس واقعی در CI برآورده شد؛ در مرحلهٔ پذیرش، اجرای محلی روی سیستم شما الزامی است.

## ۳) پلن B آزمایشی (فقط در صورت نیاز)

اگر اجرای محلی Postgres بین سندباکس و CI لازم شود (بدون Docker و root)، باینری‌های embedded-postgres بدون root در فازهای بعدی به‌عنوان ابزار توسعه آزمایش می‌شود؛ **در Phase 2 همین مسیر با `pgserver` یک‌بار به‌صورت ad-hoc تست شد** (وابستگی ثبت‌نشده، فقط ابزار تأیید).

## ۴) Runbook پذیرش محلی (پیش‌نویس — نهایی در Phase 8)

1. کلون ریپو → `cp .env.example .env` و تنظیم مقادیر.
2. `docker compose up -d --build` → healthcheck هر چهار سرویس سبز.
3. `docker compose exec backend alembic upgrade head` (از Phase 3).
4. اجرای دستی سناریوی §۵ `testing-strategy.md`.
5. Backup/Restore drill طبق مستند Phase 8.

دستورات دقیق PowerShell برای همین مرحله: README.md §اجرای محلی.

## ۵) پیامدهای دیگر محیط

- فرایندهای طولانی در سندباکس باید در یک turn تمام شوند؛ نتایج در فایل ذخیره می‌شود.
- حجم دیسک (~8GB) برای buildهای هم‌زمان backend+frontend کافی ولی نه بی‌دغدغه؛ prune دوره‌ای در CI.
- هیچ سرویسی از MarginPilot اکنون در سندباکس اجرا نیست؛ «اجرا شدن» فقط پس از Docker/CI/محلی معنا دارد.
