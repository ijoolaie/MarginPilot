# استراتژی تست MarginPilot (Phase 1)

**قانون غیرقابل مذاکره:** هیچ تستی برای سبز شدن CI حذف، skip یا دستکاری نمی‌شود. هیچ نتیجهٔ تستی بدون اجرای واقعی اعلام نمی‌شود.

## ۱) هرم تست و ابزارها

| لایه | ابزار | محدوده | جایی که اجرا می‌شود |
|---|---|---|---|
| Unit — Domain | pytest | موتور محاسبه (سود، حاشیه، گرد کردن، تخصیص)، تطبیق قیمت، نرمال‌سازی نام، گذار وضعیت — **توابع خالص، بدون DB** | سندباکس + CI + محلی |
| Unit — Service | pytest (mock فقط برای مرزهای خارجی: زمان، ایمیل) | قوانین تجاری ماژول‌ها | سندباکس + CI |
| API / Integration | pytest + httpx (ASGI) + **PostgreSQL واقعی** + Alembic | endpointها، Authorization، Tenant Isolation، تراکنش، pipeline کامل import و محاسبه | **CI با سرویس postgres؛ محلی با compose** — mock جایگزین integration نیست |
| Security | pytest (suite اختصاصی) | IDOR بین tenantها، Privilege Escalation، SQL Injection payloadها، XSS، CSRF، آپلود مخرب، Brute force، Session abuse | CI + محلی |
| Frontend Unit | Vitest | فرم و اعتبارسنجی (RHF+Zod)، جداول/فیلترها، stateهای loading/error/empty، فرمت اعداد فارسی | سندباکس + CI |
| E2E | Playwright (Node) | سناریوی کامل ۱۰ مرحله‌ای §۵ | CI (headless) + محلی |
| Performance | اسکریپت httpx/locust سبک | فایل کوچک/متوسط/بزرگ مجاز، درخواست هم‌زمان، pagination، گزارش سنگین | CI + محلی (عدد نهایی روی سیستم کاربر) |

**تقسیم محیط‌ها (مطابق محدودیت سندباکس — `environment-limitations.md`):**
- **سندباکس:** فقط unit tests و بررسی‌های مستندات/ساختار (بدون Docker/PostgreSQL).
- **CI (GitHub Actions):** lint، type-check، unit، **integration با PostgreSQL واقعی**، build دو سرویس، اسکن وابستگی و Secret.
- **سیستم محلی شما:** `docker compose up` + اجرای دستی سناریوها — بخش الزامی معیار پذیرش.

## ۲) قواعد تست

1. محاسبات پولی فقط با `Decimal`؛ در تست‌ها هرگز float وارد assertion نمی‌شود.
2. هر فرمول حداقل این پوشش را دارد: حالت عادی، مرز صفر، منفی، داده ناقص، گرد کردن.
3. `formula_version` باید در خروجی تست‌های موتور حاضر باشد (بازتولیدپذیری).
4. Integrationها از migration واقعی Alembic شروع می‌شوند (نه create_all).
5. Seed دادهٔ تست با builder/fixture — بدون وابستگی به ترتیب اجرا.
6. پوشش هدف: ماژول `pricing` ≥ ۹۰٪ statement؛ کل backend ≥ ۷۰٪ در ابتدا (در CI به‌صورت gate گزارش می‌شود).
7. تست جدید برای هر باگ قبل از fix (regression lock).
8. **Coverage اثبات صحت مالی نیست** (تصمیم بازبینی): درصد پوشش فقط نشان می‌دهد چیزی اجرا شده؛ صحت فرمول‌ها فقط با بردارهای مرجع دستی‌قابل‌راستی‌آزمایی (`calculation-principles.md §۸`) ثابت می‌شود که مستقل از کد، با محاسبهٔ دستی بازبینی می‌شوند.

## ۳) بردارهای مرجع و سوییت‌های الزامی بازبینی

**بردارهای مرجع مالی:** ۲۰ بردار در `calculation-principles.md §۸` (نسخهٔ FV-2) تعریف شده‌اند و پیاده‌سازی موتور در Phase 8 باید هر یک را به‌صورت unit test با خروجی دقیقِ ثبت‌شده سبز کند — شامل: گارد شمارش دوگانهٔ تخفیف (V6)، مرجوعی جزئی با variance علامت‌دار در دو جهت (V8/V8b)، مرجوعی کامل (V16)، تخصیص پس از مرجوعی (V20)، دورهٔ بدون فروش (V15)، هزینهٔ سفارش لغوشده (V17)، cost نامشخص (V18).

**سوییت‌های الزامی افزوده‌شده طبق بازبینی:**

| سوییت | محدوده | لایهٔ اجرا |
|---|---|---|
| یکپارچگی FK بین‌tenant | تلاش برای insert/به‌روزرسانی رکورد با والد tenant دیگر → FK violation از DB | Integration (واقعی، چون قید در DB است) |
| IDOR همهٔ منابع | هر endpoint با id منابع tenant دیگر → 404 | Integration |
| Idempotency هم‌زمان | دو درخواست موازی با همان key → یکی اجرا و دیگری پس از commit اول **replay پاسخ ذخیره‌شده** می‌کند (`ON CONFLICT` + `SELECT FOR UPDATE` — بدون وضعیت in-progress)؛ rollback اول → دوم خودش اجرا می‌کند؛ همان key با درخواست متفاوت → `IDEMPOTENCY_CONFLICT`؛ **کلید منقضی:** دو درخواست رقیب → اولی بازنشانی اتمیک و اجرا، دومی replay پاسخ جدید؛ rollback بعد از بازنشانی → retry دوباره ممکن | Integration |
| اتمی بودن Import و retry | شکست در میانهٔ commit → rollback کامل + کلید idempotency آزاد + retry موفق | Integration |
| مرجوعی کامل/جزئی + تخفیف + تخصیص | تعامل مرجوعی با line_discount، order_discount_share و هزینه‌های order-scoped (بردارهای V8/V8b/V16/V20)؛ چند مرجوعی مستقل روی یک قلم (تا سقف مقدار باقی‌مانده) با رکوردهای sales_returns/sales_return_items و هم‌زمانی امن با lock | Unit + Integration |
| Snapshot تاریخی | تغییر قیمت خرید/فروش محصول پس از ثبت سفارش → سود سفارش قبلی تغییر نمی‌کند؛ تاریخچهٔ قیمت درست ثبت می‌شود | Integration |
| پذیرش Backup/Restore | بازیابی کامل dump روی محیط تمیز + سلامت داده | محلی + CI (Phase 14) |
| پذیرش PDF فارسی/RTL | پروتوتایپ گزارش فارسی RTL با فونت وزیرمتن **در ابتدای مسیر گزارش‌گیری** (قبل از آن‌که Phase 11 «تمام» اعلام شود) — کشف مشکلات فونت/RTL به پایان پروژه موکول نمی‌شود | Unit + دستی |

## ۴) E2E — سناریوی پذیرش کامل

1. ثبت‌نام → 2. ایجاد کسب‌وکار (tenant) → 3. ثبت محصول → 4. ثبت تأمین‌کننده → 5. بارگذاری فایل فروش → 6. تطبیق ستون‌ها (mapping) → 7. تأیید اطلاعات (preview/confirm) → 8. محاسبهٔ سود → 9. مشاهدهٔ داشبورد → 10. تولید گزارش.
هر مرحله assertion مشخص دارد (مثلاً مرحلهٔ ۷: تعداد ردیف valid/خطا با انتظار file fixture برابر باشد).

## ۵) Performance — ماتریس فایل

| سنجه | کوچک | متوسط | بزرگ (سقف مجاز) |
|---|---|---|---|
| ردیف | ~۱۰۰ | ~۵,۰۰۰ | ۱۰۰,۰۰۰ (`IMPORT_MAX_ROWS`) |
| انتظار | < 2s parse+validate | < 15s | بودجهٔ زمانی تست CI؛ حداکثر 5min |
| معیار | بدون OOM؛ خطاها کامل | اتمی بودن commit | حافظهٔ ثابت (streaming read_only) |

هم‌زمانی: ۵۰ درخواست خواندن هم‌زمان روی pagination — پاسخ p95 ثبت و مقایسهٔ دوره‌ای.

## ۶) CI Gates (از Phase 2)

Lint (ruff) → Type check (mypy) → Unit → Integration (postgres service) → Frontend lint/type/test → Build هر دو سرویس → pip-audit/npm audit → gitleaks. شکست هر مرحلهٔ ضروری = توقف انتشار. Threshold پوشش به‌صورت flag گزارش می‌شود.

## ۷) تعریف «تمام‌شده» برای هر قابلیت

کد + تست سبز در CI (نه فقط محلی) + مستند به‌روز + آیتم‌های وضعیت `IMPLEMENTED`/`TESTED`/`VERIFIED` فقط با شواهد اجرا (خروجی تست). مطابق شرط G: هیچ ادعایی بدون خروجی واقعی.

## Phase 4 Step 3 import test coverage

- Parser unit tests: UTF-8-BOM and Windows-1256 CSV, delimiter detection, empty/duplicate headers, row/column limits, malformed/binary CSV, XLSX visible-sheet parsing, macro/zip-bomb rejection, exact mapping constraints, Persian digit/unit normalization, Decimal scale/range and duplicate classification.
- API integration tests on PostgreSQL: upload and metadata, product preview/commit, price-history provenance, supplier-price import as draft, explicit finalization, error-row pagination and XLSX report, formula neutralization, tenant isolation, RBAC, invalid extension/MIME, XLSX upload, idempotent replay and atomic rollback/retry.
- The original upload bytes must not be present in the import database records or written to a project upload directory; only raw parsed row objects and the SHA-256 digest are retained.
