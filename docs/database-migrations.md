# راهنمای Migration دیتابیس

## محدودهٔ این مرحله

اولین Migration فقط جداول سراسری هویت، چندمستاجری و زیرساخت را ایجاد می‌کند: `users`، `tenants`، `roles`، `permissions`، `role_permissions`، `memberships`، `sessions`، `password_reset_tokens`، `tenant_settings`، `audit_logs` و `idempotency_keys`.

جداول دامنهٔ محصول، تأمین‌کننده، فروش، هزینه، import، محاسبه و گزارش در این Migration ساخته نمی‌شوند؛ آن‌ها باید همراه با پیاده‌سازی مرحله‌ای ماژول‌های مربوط اضافه شوند. تعریف ORM جای Migration را نمی‌گیرد و `Base.metadata.create_all()` در مسیر اجرا/استقرار مجاز نیست.

## اجرای محلی بدون Docker

از پوشهٔ `backend` و با محیط مجازی پروژه:

```powershell
$env:DATABASE_URL = "postgresql+psycopg://<user>:<password>@localhost:5432/marginpilot"
alembic upgrade head
alembic current
alembic check
```

## اجرای محلی با Docker Compose

ابتدا PostgreSQL را با Compose بالا بیاورید و Healthy شدن آن را بررسی کنید؛ سپس Migration را به‌عنوان یک کار یک‌باره اجرا کنید:

```powershell
docker compose up -d postgres
# پس از Healthy شدن PostgreSQL:
docker compose run --rm backend alembic upgrade head
docker compose up -d
```

فایل Docker مربوط به Backend، `alembic.ini` و پوشهٔ `alembic/` را در image قرار می‌دهد. Migration عمداً در startup برنامه اجرا نمی‌شود تا چند replica هم‌زمان برای تغییر schema رقابت نکنند و خطای Migration مانع تشخیص مستقل وضعیت برنامه نشود.

## قواعد استقرار

1. پیش از Migration تولیدی، backup معتبر و امکان بازیابی آن بررسی شود.
2. Migration به‌صورت job یک‌باره و با همان نسخهٔ image برنامه اجرا شود؛ سپس نسخهٔ Backend مستقر شود.
3. استقرار تولیدی فقط رو به جلو است. `downgrade` برای آزمون و محیط توسعه است؛ در صورت خطای schema تولیدی، اصلاحیهٔ forward-only تهیه شود.
4. هر Migration باید روی PostgreSQL واقعی در CI، شامل `upgrade head`، `alembic check` و آزمون downgrade/upgrade در دیتابیس دورریختنی، بررسی شود.
5. Extension موردنیاز `citext` در Migration ایجاد می‌شود. دسترسی لازم برای ایجاد Extension باید در نقش دیتابیس migration وجود داشته باشد.

## داده‌های اولیهٔ RBAC

Migration نقش‌های سیستمی `owner`، `admin`، `analyst`، `viewer` و `platform_admin` و ۲۰ کد مجوز مصوب در `security.md` را به‌صورت idempotent seed می‌کند. `platform_admin` عمداً هیچ مجوز tenant-level ندارد. هیچ کاربر، رمز عبور، tenant یا دادهٔ نمونه‌ای seed نمی‌شود.
