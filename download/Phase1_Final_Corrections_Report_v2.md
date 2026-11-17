# گزارش اصلاحات دور سوم بازبینی — MarginPilot Phase 1

**تاریخ:** ۲۰۲۶-۱۱-۱۶ · **دامنه:** فقط چهار یافتهٔ بازبینی ZIP سوم + ایراد اسکریپت آرشیو؛ معماری و تصمیم‌های تأییدشدهٔ قبلی دست‌نخورده ماندند.

## ۱) فایل‌های اصلاح‌شده با موقعیت دقیق

| # | فایل : خط | تغییر |
|---|---|---|
| 1 | docs/data-model.md:180 | ایندکس `sales_returns`: `UNIQUE (tenant_id, return_number)` — **حذف `WHERE deleted_at IS NULL`** (جدول نه ستون deleted_at دارد نه soft-delete؛ رکورد تغییرناپذیر است) |
| 2 | docs/data-model.md:231 | §۸ فهرست indexها: `sales_returns(tenant_id, return_number)` از partial unique به **unique بدون partial** |
| 3 | docs/api-contract.md:23-29 | §۱.۵ بازنویسی کامل جریان با **الگوریتم اجرایی PostgreSQL-معتبر** (گام ۱ رزرو اتمیک، گام ۲ مالک، گام ۳ انتظار) + ردیف‌های TTL/کلید منقضی و رقابت کلید منقضی |
| 4 | docs/data-model.md:139 | مشخصات `idempotency_keys`: الگوریتم + رفتار کلید منقضی (بازنشانی اتمیک، سریال‌سازی توسط arbiter) |
| 5 | docs/decisions.md:121-124 | **ADR-023 بازنگری شد**: رزرو با `INSERT … ON CONFLICT … DO UPDATE … WHERE expires_at <= now() RETURNING id` + `SELECT … FOR UPDATE`؛ دلیل نادرستی متن قبلی مستند شد |
| 6 | docs/decisions.md:109 | ADR-021: تعریف هش به تعریف کامل (method+path+operation+body) هماهنگ شد |
| 7 | docs/testing-strategy.md:43 | سوییت تست Idempotency: replay/rollback/hash-mismatch + سناریوی کلید منقضی با دو رقیب |
| 8 | docs/architecture.md:119 | شمارش FK مرکب: **۲۱ → ۲۴** |
| 9 | docs/decisions.md:91 | ADR-018: شمارش FK مرکب: **۲۱ → ۲۴** |
| 10 | scripts/make_phase1_zip.sh | بازنویسی کامل — بند ۵ پایین |

گزارش‌های تاریخی قبلی (download/*.md دورهای قبل) عمداً بازنویسی نشدند.

## ۲) الگوریتم Idempotency — روش اجرایی انتخاب‌شده

**مدل:** تراکنش واحد با رزرو اتمیک کلید — بدون SAVEPOINT، بدون وضعیت processing.

**گام ۱ — رزرو (یک statement):**
```sql
INSERT INTO idempotency_keys (tenant_id, user_id, idempotency_key, operation,
                              request_hash, created_at, expires_at)
VALUES (…, now(), now() + INTERVAL '24 hours')
ON CONFLICT (tenant_id, user_id, idempotency_key)
DO UPDATE SET operation       = EXCLUDED.operation,
              request_hash    = EXCLUDED.request_hash,
              response_status = NULL,
              response_body   = NULL,
              created_at      = now(),
              expires_at      = now() + INTERVAL '24 hours'
WHERE idempotency_keys.expires_at <= now()
RETURNING id;
```
- **RETURNING ردیف داد** → این درخواست مالک کلید است (دو حالت: INSERT تازه، یا بازنشانی اتمیک رکورد منقضی).
- **RETURNING خالی** → رکورد زندهٔ دیگری وجود دارد.

**چرا این معتبر است و متن قبلی نبود:** در PostgreSQL، `unique violation` خام تراکنش را به وضعیت aborted می‌برد و ادامهٔ همان تراکنش بدون SAVEPOINT ممکن نیست — ایراد درست بازبینی. اما `ON CONFLICT` با شرط WHERE ناموفق، فقط skip می‌کند و **تراکنش زنده و قابل ادامه می‌ماند**؛ ضمناً arbiter قید یکتایی خودش تا پایان تراکنش مالک منتظر می‌ماند، پس نیازی به مکانیسم انتظار دستی نیست.

**گام ۲ — مسیر مالک:** اجرای عملیات + ثبت response_status/body در همان تراکنش → COMMIT.

**گام ۳ — مسیر انتظار (RETURNING خالی):** INSERT تا پایان تراکنش مالک در arbiter قفل می‌شود؛ سپس:
- **COMMIT مالک** → WHERE روی رکورد committed ارزیابی: unexpired → skip → همان تراکنش با `SELECT … FOR UPDATE` رکورد را می‌خواند (فوری) → مقایسهٔ `request_hash`: متفاوت → `409 IDEMPOTENCY_CONFLICT` (بدون اجرای عملیات)؛ یکسان → replay پاسخ با `Idempotent-Replayed: true` → `ROLLBACK` (فقط خوانده شده).
- **ROLLBACK مالک** → ردیف هرگز دیده نمی‌شود → INSERT به‌صورت عادی موفق → مسیر مالک (گام ۲).

**رفتار TTL (بازبینی دور سوم):**
1. پس از ۲۴ ساعت همان key برای **اجرای جدید** آزاد است.
2. رکورد منقضی حتی پیش از پاک‌سازی، قید را عملاً اشغال نمی‌کند: در گام ۱ با `DO UPDATE … WHERE expires_at <= now()` **اتمیک** به رکورد تازهٔ کامل (operation/hash/created_at/expires_at جدید، پاسخ خالی) بازنشانی می‌شود.
3. اگر عملیات جدید rollback شود، بازنشانی هم rollback می‌شود و رکورد کهنهٔ منقضی سر جایش می‌ماند → retry دوباره ممکن.
4. رقابت دو درخواست هم‌زمان برای کلید منقضی: arbiter سریال می‌کند — اولی WHERE برقرار → بازنشانی → مالک؛ دومی رکورد تازهٔ unexpired می‌بیند → WHERE نادرست → مسیر انتظار → پس از commit اولی، replay پاسخ جدید.
5. پاک‌سازی دوره‌ای رکوردهای منقضی (index(expires_at)) فقط بهداشت داده است؛ صحت قرارداد به آن وابسته نیست.

رفتار یکسان در: api-contract §۱.۵ (خطوط ۲۳-۲۹)، data-model §۵ (خط ۱۳۹)، ADR-021/023، سوییت تست (testing-strategy خط ۴۳).

## ۳) اصلاح ایندکس sales_returns (P0)

جدول مرجوعی بدون soft-delete و تغییرناپذیر است؛ ایندکس به `UNIQUE (tenant_id, return_number)` ساده اصلاح شد (data-model خطوط ۱۸۰ و ۲۳۱). پیامد مستند: return_number پس از ثبت هرگز آزاد نمی‌شود — با تغییرناپذیری رکوردها سازگار است. هیچ ستون soft-delete اضافه نشد.

## ۴) هماهنگ‌سازی شمارش FK (P2)

architecture.md:119 و ADR-018 (decisions.md:91): ۲۱ → **۲۴**. اسکن `grep "۲۱ FK"` روی کل docs/: بدون یافته. گزارش‌های تاریخی دست‌نخورده.

## ۵) اصلاح اسکریپت ZIP — ریشهٔ باگ و راه‌حل

**ریشه:** Info-ZIP در `-x` از الگوی نفی (`!`) پشتیبانی نمی‌کند؛ الگوی `.env.*` فایل `.env.example` را هم حذف می‌کرد، در حالی که manifest آن را هش می‌زد — هش بدون فایل داخل آرشیو بی‌ارزش بود.

**اصلاحات make_phase1_zip.sh:**
1. `.env.example` پس از excludeها **صریحاً** به آرشیو اضافه می‌شود (بند ۲ اسکریپت).
2. گارد fail-fast: اگر `.env` واقعی داخل آرشیو باشد → توقف با خطا؛ اگر هر یک از .env.example، README، همهٔ docs/*.md و ۵ گزارش نباشند → توقف با خطا (بند ۳).
3. Manifest برای هر فایلِ هش‌شده، **تطبیق بایت‌به‌بایت با محتوای آرشیو** (`unzip -p | sha256sum`) انجام می‌دهد؛ هر عدم تطابق → توقف. خروجی: خطوط `MATCH  <hash>  <file>`.
4. تعداد **واقعی** فایل‌های آرشیو در خروجی و پایان manifest اعلام می‌شود.
5. `unzip -t` اجباری در پایان.
6. یادداشت صریح در manifest: `.git` عمداً آرشیو نمی‌شود؛ manifest خودش شواهد git است (HEAD، وضعیت working tree، اثبات ignore شدن .env).

## ۶) شواهد اجرای واقعی (خروجی اسکریپت — ۲۰۲۶-۱۱-۱۶)

1. **ساخت آرشیو:** `bash scripts/make_phase1_zip.sh` → `No errors detected in compressed data` · **`ARCHIVE OK … real file count: 55`** (۵۵ فایل واقعی).
2. **تأیید ایراد گزارش‌شده رفع شد:** `unzip -l` شامل `.env.example` (۲۱۸۴ بایت، در ریشهٔ آرشیو) — بدون گارد جدید، همین مرحله قبلاً بی‌سروصدا می‌شکست.
3. **تطبیق هش ↔ محتوای آرشیو:** manifest شامل **۱۱ خط MATCH** است — برای هر فایل، `sha256sum` منبع با `unzip -p | sha256sum` (محتوای استخراج‌شده از آرشیو) برابر شد:
   - `.env.example` = `476ab1a6…535862` ✓ · README.md ✓ · docs/api-contract.md ✓ · docs/architecture.md ✓ · docs/calculation-principles.md ✓ · docs/data-model.md ✓ · docs/decisions.md ✓ · docs/dependencies.md ✓ · docs/environment-limitations.md ✓ · docs/security.md ✓ · docs/testing-strategy.md ✓
4. **گارد .env واقعی:** `git check-ignore .env` → YES؛ خروجی `unzip -l` هیچ ردیفی به‌شکل `\.env$` ندارد (فقط `.env.example`)؛ ضمناً گارد اسکریپت در صورت ورود .env با خطای FATAL متوقف می‌شد.
5. **وضعیت git در لحظهٔ ساخت:** HEAD=`d77e4ea9…` (main)؛ تغییرات این دور (۸ فایل + zip + این گزارش) بدون commit در working tree — کامل در `PHASE1_MANIFEST.txt` ثبت شده.
6. **فایل‌های شواهد داخل آرشیو:** هر ۵ گزارش بازبینی + `PHASE1_MANIFEST.txt`.

## ۷) اعلام صریح: چه چیزهایی فقط طراحی‌اند و تست اجرایی نشده‌اند

- **الگوریتم Idempotency دور سوم** (ON CONFLICT/RETURNING/FOR UPDATE): مستند و از نظر معنای PostgreSQL بررسی شده، اما **اجرا نشده** — تست اجرایی آن (تست‌های سوییت خط ۴۳) در Phase 3+ انجام می‌شود.
- رفتار TTL و رقابت کلید منقضی: فقط طراحی؛ در محیط PostgreSQL واقعی آزمایش نشده.
- همهٔ قیدهای DB (FKهای مرکب، سه‌ستونه، uniqueها، CHECKها): طراحی DDL؛ **هیچ migration اجرا نشده**.
- موتور محاسبات/بردارهای V: درست‌سنجی عددی مستند، بدون اجرا.
- ماتریس سازگاری نسخه‌ها و PDF فارسی/RTL: به Phaseهای بعدی موکول.
- وضعیت git: تغییرات این دور **بدون commit** در working tree است؛ commitهای UUID (d77e4ea و قبلی‌ها) checkpoint خودکار محیط بودند، نه اقدام من.

## ۸) مرزها — تأیید

✅ Phase 2 شروع نشد · هیچ قابلیت محصولی پیاده نشد · هیچ migration/Docker/نصب وابستگی انجام نشد · معماری تغییر نکرد · هیچ commit/push/merge انجام نشد · فقط فایل‌های مرتبط با چهار یافته + اسکریپت + این گزارش تغییر کردند.
