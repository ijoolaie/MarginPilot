# گزارش تکمیل اصلاحات — Round 2 (Phase 2 / Step 1)

**تاریخ:** ۲۰۲۶-۱۱-۱۷ · **محدوده:** فقط یافتهٔ باقی‌ماندهٔ ممیزی Round 1 (تکمیل Redaction رمزهای URL-encoded در P2-05). هیچ فایل نامرتبطی تغییر نکرد؛ هیچ قابلیت محصولی اضافه نشد؛ Phase 2 / Step 2 و Phase 3 شروع نشدند؛ هیچ commit/push/merge انجام نشده.

**نتیجهٔ گیت‌ها پس از اصلاح (اجرای واقعی، شواهد در `download/evidence/*_r2.txt`):**
Ruff ✓ (0 خطا) · mypy strict ✓ (۲۲ فایل) · pytest **۳۹ unit** (بود ۳۶؛ +۳ تست جدید) + **۳ integration با PostgreSQL واقعی** ✓

---

## P2-05 (تکمیل) — Redaction شکل URL-decoded password ✅

**تغییرات:**
- `backend/app/core/logging.py:20` — import `unquote` در کنار `urlsplit`.
- `backend/app/core/logging.py:41-56` — `secret_fragments` اکنون سه شکل را برمی‌گرداند:
  1. کامل DSN (رفتار قبلی، حفظ شده — عنصر اول فهرست)،
  2. password به همان شکلی که در URL نوشته شده (percent-encoded؛ رفتار قبلی)،
  3. **شکل URL-decoded همان password** با `urllib.parse.unquote` (جدید).
- قواعد درج (طبق ممیزی): مقدار خالی وارد نمی‌شود (`if candidate`) و مقدار تکراری وارد نمی‌شود (`candidate not in fragments`) — پسورد بدون کاراکتر escape فقط یک‌بار در فهرست است و طول فهرست در حالت معمولی همان ۲ می‌ماند.
- docstring تابع و docstring ماژول (`logging.py:6-11`) دقیقاً همین رفتار را مستند می‌کنند.
- فرمت‌کن‌ها (`JsonFormatter`/`ConsoleFormatter`) و `redact_secrets` بدون تغییر — مصرف‌کنندگان همان `Sequence[str]` را می‌گیرند؛ scrub پیام + traceback روی خروجی نهایی و حفظ `request_id` كما پیش.

**تست‌های جدید (`backend/tests/unit/test_request_lifecycle.py`):**
- ثابت‌های تست: `:22-25` — `ENCODED_PASSWORD = "p%40ss%21w0rd"`، `DECODED_PASSWORD = "p@ss!w0rd"`، `ENCODED_DSN` با password URL-encoded (معتبر از نظر validator دامنه‌اش هم هست).
- `test_secret_fragments_include_url_decoded_password` (`:155-165`) — فهرست شامل DSN کامل + شکل encoded + شکل decoded؛ طول دقیقاً ۳ (بدون تکرار) و بدون عضو خالی.
- `test_secret_fragments_plain_password_no_duplicates` (`:167-170`) — pin رفتار قبلی: پسورد معمولی بدون escape → فهرست دقیقاً `(DSN, password)` و نه بیشتر.
- `test_json_formatter_scrubs_both_password_shapes` (`:172-190`) — متن خطا یک‌بار password encoded و یک‌بار password decoded دارد (هم در پیام رکورد، هم در exception ای که به traceback می‌رود)؛ assertion: هیچ‌یک از دو شکل در خروجی (پیام یا traceback) باقی نمی‌ماند، دقیقاً ۴ `[REDACTED]` (۲ شکل × پیام + traceback) باقی می‌ماند و هر دو فیلد `event` و `exc_info` مارکر را دارند.

**چرا این تکمیل لازم بود:** متن استثناهای واقعی (مثلاً پیام احراز هویت درایور) ممکن است password را **decode شده** نقل کند در حالی که DSN کامل آن را percent-encoded نگه می‌دارد؛ scrub قبلی فقط شکل encoded و DSN را می‌پوشاند.

---

## یادداشت محیطی (شفاف‌سازی)

سندباکس بین دو دور بازیابی شد و venv از دست رفته بود؛ وابستگی‌ها **دوباره از همان `backend/requirements.lock` با `pip install --require-hashes`** نصب شدند (مسیر گیت ۴ CI) — این خودٌ یک اجرای دیگرِ گیت «نصب clean از lock هش‌دار» است. نسخه‌های نصب‌شده مطابق pin: fastapi 0.163.1، sqlalchemy 2.1.8، ruff 0.17.5، mypy 2.4.1. (دو هشدارِ conflict مربوط به ابزارهای جانبی سندباکس مثل gradio است و به backend مربوط نیست.)

## وضعیت واقعی Docker و CI (اعلام صریح)

- **Docker: اجرا نشده است.** Dockerfileها، `docker-compose.yml` و `Caddyfile` فقط فایل‌اند؛ سندباکس Docker daemon ندارد.
- **CI: اجرا نشده است.** `.github/workflows/ci.yml` فقط فایل است؛ سندباکس runner ندارد.
- PostgreSQL واقعی فقط به‌صورت embedded (سوکت محلی، بدون mock/SQLite) در تست‌های integration اجرا شد: `download/evidence/backend_integration_tests_r2.txt`.

## فایل‌های تغییر یافته (فقط مربوط به این یافته)

`backend/app/core/logging.py` · `backend/tests/unit/test_request_lifecycle.py`

**شواهد رِ-رِان:** `download/evidence/backend_lint_type_test_r2.txt` · `download/evidence/backend_integration_tests_r2.txt`
