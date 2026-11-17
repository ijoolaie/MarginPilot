# گزارش اصلاحات دور پنجم — MarginPilot Phase 1 (بر اساس ممیزی ZIP چهارم)

**تاریخ:** ۲۰۲۶-۱۱-۱۶ · **دامنه:** فقط سه یافتهٔ P1 (زمان TTL، nullability پاسخ، Isolation) + یک P2 (شمارش آرشیو)؛ بقیهٔ طراحی دست‌نخورده.

## ۱) فایل‌های اصلاح‌شده با موقعیت دقیق

| # | فایل : خط | تغییر |
|---|---|---|
| 1 | docs/api-contract.md:23 | گام ۱: همهٔ `now()` → `clock_timestamp()` (در VALUES، SET و شرط WHERE)؛ شروع تراکنش به `BEGIN ISOLATION LEVEL READ COMMITTED` تغییر کرد |
| 2 | docs/api-contract.md:24 | گام ۲: مقداردهی **هم‌زمانِ** response_status و response_body پیش از COMMIT + ارجاع به CHECK یکنواختی |
| 3 | docs/api-contract.md:27 | ردیف TTL: شرط بازنشانی به `expires_at <= clock_timestamp()` |
| 4 | docs/api-contract.md:29 | ردیف جدید «زمان‌بندی»: چرا now() ممنوع است + تعریف TTL به‌صورت wall-clock |
| 5 | docs/api-contract.md:30 | ردیف جدید «مرز TTL با رقابت»: مثال دو درخواست B/C در عبور از مرز انقضا |
| 6 | docs/api-contract.md:31 | ردیف جدید «سطح Isolation»: READ COMMITTED الزامی + دلایل ساختاری |
| 7 | docs/api-contract.md:32 | ردیف جدید «رفتار Serialization Failure»: SQLSTATE 40001 → retry کامل از گام ۱ (≤۳ بار) → 503 retriable |
| 8 | docs/data-model.md:139 | مشخصات idempotency_keys: nullable بودن و چرخهٔ عمر هر دو فیلد پاسخ + `CHECK ((response_status IS NULL) = (response_body IS NULL))` + زمان‌ها و شرط انقضا با clock_timestamp |
| 9 | docs/decisions.md:109 | ADR-021: قاعدهٔ یکنواختی snapshot پاسخ + زمان واقعی statement (clock_timestamp) + تراکنش READ COMMITTED |
| 10 | docs/decisions.md:120-124 | ADR-023 با عنوان «بازنگری دور پنجم»: statement با clock_timestamp، دلیل ساختاری READ COMMITTED، رفتار serialization retry، جایگزین‌های ردشدهٔ جدید (ساعت اپلیکیشن، statement_timestamp) |
| 11 | scripts/make_phase1_zip.sh:2-9,40-45,63-66,75-77,84-92 | شمارش جداگانهٔ فایل/پوشه/ورودی + نوشتن composition در manifest + خودراستی‌آزمایی پس از zip |
| 12 | download/Phase1_Final_Corrections_Report_v3.md | همین گزارش |

فیلتر تأیید: `grep -rn "now()" docs/` فقط یک تطبیق دارد — توضیحِ ممنوعیت now() در ADR-023 (خط ۱۲۲)، نه استفادهٔ واقعی. گزارش‌های تاریخی دورهای قبل بازنویسی نشدند.

## ۲) اصلاح زمان TTL — P1

**ایراد ممیز درست بود.** در PostgreSQL سه زمان‌سنج وجود دارد: `now()`/`transaction_timestamp()` (زمان شروع تراکنش)، `statement_timestamp()` (شروع statement جاری) و `clock_timestamp()` (ساعت واقعی در لحظهٔ ارزیابی). در الگوریتم ما، تراکنش درخواست دوم ممکن است **قبل** از انقضای کلید BEGIN شود، اما داخل statement اول (arbiter قید یکتایی) پشت قفل تراکنش مالک منتظر بماند و فقط **بعد** از commit/rollback مالک به ارزیابی `WHERE` برسد. با `now()`، آن ارزیابی هنوز زمانِ پیش از انقضا را می‌بیند و کلید واقعاً منقضی «تازه» تلقی می‌شود — یعنی replay پاسخ کهنه یا ردِ بازنشانی، در حالی که TTL تمام شده است.

**تصمیم یکسان در هر چهار سند (api-contract §۱.۵، data-model §۵، ADR-021، ADR-023):**
1. **شرط انقضا:** `WHERE idempotency_keys.expires_at <= clock_timestamp()` — ارزیابی با ساعت واقعی DB در لحظهٔ رسیدن به WHERE.
2. **نوشتن زمان‌ها:** created_at و expires_at در رزرو اولیه و در بازنشانی، هر دو با `clock_timestamp()` — یعنی TTL دقیقاً «۲۴ ساعت wall-clock از لحظهٔ رزرو/بازنشانی» است، مستقل از طول عمر تراکنش. تعریف نوشتن و ارزیابی یکسان است؛ هیچ اختلاط transaction-time و wall-clock باقی نمانده.
3. **مرز TTL با رقابت** (api-contract:30): تصمیم هر درخواست با clock_timestamp() لحظهٔ ارزیابی (پس از آزاد شدن قفل arbiter) است و arbiter درخواست‌ها را سریال می‌کند، پس در هر پنجرهٔ انقضا حداکثر یک درخواست می‌تواند جایگزین شود. مثال مستند: A در حال اجرا، کلید در میان انتظار منقضی می‌شود → B پس از commit A شرط را برقرار می‌بیند → بازنشانی و اجرا؛ C پشت قفل B رکورد تازه می‌بیند → مسیر انتظار → replay پاسخ B. اگر B پیش از انقضا ارزیابی کند، B replay می‌کند و C جایگزین می‌شود — در هر دو صورت سریال و سازگار.
4. **جایگزین‌های ردشده** (ADR-023): ساعت اپلیکیشن (WHERE باید در همان statement arbiter اجرا شود؛ drift ساعت اپ کلاینت‌ها ریسک دارد)، `statement_timestamp()` (در statementهای بعدی مسیر مالک معنای ناهمگون می‌سازد).

## ۳) Nullability و قاعدهٔ یکنواختی پاسخ — P1

در data-model.md:139 اکنون صریح است:
- `response_status` و `response_body (jsonb)` هر دو **nullable**؛
- **رزرو اولیه:** هر دو NULL (statement گام ۱ آن‌ها را مقدار نمی‌دهد)؛
- **پس از اجرای موفق:** هر دو پیش از COMMIT و با هم مقداردهی می‌شوند (api-contract:24)؛
- **بازنشانی کلید منقضی:** SET صریح هر دو به NULL در همان statement گام ۱؛
- **قاعدهٔ یکنواختی در سطح DB:** `CHECK ((response_status IS NULL) = (response_body IS NULL))` — هیچ رکوردی نمی‌تواند فقط یک‌ضلعی مقدار داشته باشد؛ نیمه‌کاره‌بودن هم ناممکن است چون مقداردهی در همان تراکنشی رخ می‌دهد که خودش کلاً commit یا rollback می‌شود.

## ۴) سطح Isolation — P1

- **READ COMMITTED الزامی** (api-contract:31، ADR-023): middleware با `BEGIN ISOLATION LEVEL READ COMMITTED` آغاز می‌کند و اگر پیش‌فرض نشست بالاتر باشد، با `SET LOCAL` در همان تراکنش تحمیل می‌شود.
- **چرا SELECT پس از INSERT ناموفق باید snapshot تازه ببیند:** مسیر انتظار به این وابسته است که پس از پایان تراکنش مالک، `SELECT … FOR UPDATE` ردیف committed را ببیند. در READ COMMITTED هر statement snapshot جدید می‌گیرد، پس این تضمین برقرار است؛ در REPEATABLE READ/SERIALIZABLE snapshot تراکنش از BEGIN ثابت است و همان SELECT به‌جای دیدن ردیفِ پس از snapshot، خطای `could not serialize access due to concurrent update` می‌دهد. یعنی الگوریتم به READ COMMITTED وابستهٔ **ساختاری** است، نه صرفاً توصیه.
- **Serialization Failure در سطوح بالاتر** (api-contract:32): اگر deployment سطح بالاتری تحمیل کند و گام ۱ یا ۳ با `SQLSTATE 40001` شکست بخورد: retry **کامل از گام ۱** (کل INSERT/arbiter/عملیات از نو — حداکثر ۳ بار با backoff تصادفی)؛ در نهایت `503` با خطای retriable. ادامه با تراکنش aborted هرگز رخ نمی‌دهد.
- **اعلام:** این رفتارها فقط طراحی‌اند؛ هیچ آزمایش اجرایی PostgreSQL انجام نشده.

## ۵) شمارش آرشیو — P2

- **پذیرش ایراد:** عدد ۵۵ در خروجی قبلی اسکریپت و گزارش دور سوم «تعداد کل ورودی‌ها» بود نه تعداد فایل‌ها؛ تفکیک صحیح همان آرشیو: **۳۵ فایل + ۲۰ پوشه = ۵۵ ورودی** (به تأیید ممیز). گزارش‌های تاریخی دورهای قبل عمداً بازنویسی نشدند؛ این گزارش اصلاح را ثبت می‌کند.
- **اصلاح اسکریپت:** شمارش با `unzip -Z1` و تفکیک ورودی‌های دارای `/` پایانی (پوشه) از بقیه (فایل واقعی)؛ هر سه عدد جداگانه در خروجی و در manifest؛ composition پس از افزودن manifest به آرشیو **مجدداً شمارش و با ادعای manifest مقایسه** می‌شود — عدم تطابق → FATAL و شکست اسکریپت.

## ۶) شواهد اجرای واقعی (خروجی اسکریپت — ۲۰۲۶-۱۱-۱۶)

1. **ساخت و سلامت:** `bash scripts/make_phase1_zip.sh` → `No errors detected in compressed data` · **`ARCHIVE OK … composition: 36 real files + 20 directories = 56 entries`** — سه عدد جداگانه، نه یک عدد تجمیعی.
2. **شمارش اصلاح‌شده نسبت به دور قبل:** آرشیو قبلی ۳۵ فایل + ۲۰ پوشه = ۵۵ ورودی بود (تأیید ممیز)؛ ورودی جدید، همین گزارش (v3) است → ۳۶ فایل. خودراستی‌آزمایی پس از zip (خط ۴b اسکریپت) شمارش واقعی را با ادعای manifest مقایسه کرد — بدون FATAL گذشت.
3. **composition در manifest:** خط «Archive composition: 36 real files · 20 directories · 56 entries» + یادداشت روش شمارش (`unzip -Z1`، تفکیک ورودی‌های `/`-پایانه) — قابل راستی‌آزمایی مستقل توسط ممیز.
4. **تطبیق هش ↔ محتوای آرشیو:** **۱۱ خط MATCH** — همان ۱۱ فایل دور قبل (.env.example، README، ۹ سند طراحی)؛ تغییرات این دور در همین فایل‌ها اعمال و هر هش با `unzip -p | sha256sum` بایت‌به‌بایت تأیید شد.
5. **وضعیت git در لحظهٔ ساخت:** HEAD=`a7d47390…` (main) — checkpoint خودکار محیط بین دو نوبت؛ تغییرات این دور بدون commit در working tree و کامل در manifest ثبت است.
6. **فایل‌های شواهد داخل آرشیو:** ۶ گزارش بازبینی (Phase0، Architecture، Corrective، Final Corrections، v2، v3) + `PHASE1_MANIFEST.txt`.

## ۷) وضعیت Git — گزارش‌شده، نه مستقلاً تأییدشده

یافتهٔ ممیز پذیرفته و ثبت شد: از خود ZIP نمی‌توان وضعیت git را مستقلاً با git تأیید کرد. ادعای ما نیز فقط همین است: manifest شواهد (HEAD، porcelain، اثبات ignore شدن .env) را «گزارش» می‌کند؛ `.git` عمداً در آرشیو نیست. هیچ ادعای تأیید مستقلی مطرح نشده است.

## ۸) اعلام صریح — فقط طراحی، بدون تست اجرایی

- الگوریتم Idempotency در وضعیت فعلی (clock_timestamp، مرز TTL، CHECK یکنواختی، READ COMMITTED، retry serialization): **روی PostgreSQL واقعی تست نشده** — تست‌های سوییت مربوطه در Phase 3+ اجرا می‌شوند.
- همهٔ قیدهای DB (شامل CHECK جدید): طراحی DDL؛ هیچ migration اجرا نشده.
- موتور محاسبات و بردارهای V: درست‌سنجی عددی مستند، بدون اجرا.
- ماتریس سازگاری نسخه‌ها و PDF فارسی/RTL: به Phaseهای بعدی موکول.
- تغییرات این دور بدون commit در working tree است؛ commitهای UUID checkpoint خودکار محیط‌اند.

## ۹) مرزها — تأیید

✅ Phase 2 شروع نشد · هیچ قابلیت محصولی پیاده نشد · migration/Docker/نصب وابستگی انجام نشد · معماری تغییر نکرد · commit/push/merge انجام نشد · تغییرات فقط محدود به موارد دستور ممیزی چهارم بود.
