# قرارداد API نسخهٔ ۱ — MarginPilot (نسخهٔ اصلاح‌شدهٔ بازبینی Phase 1)

**وضعیت:** قرارداد اصلاح‌شده بر اساس بازبینی فنی (یکسان‌سازی مجوزها، طراحی کامل Idempotency، گذارهای وضعیت، سیاست ثبت‌نام، منبع تاریخچهٔ قیمت). پیاده‌سازی از Phase 3؛ OpenAPI خودکار از کد FastAPI با این سند سازگار نگه داشته می‌شود.

## ۱) قواعد عمومی

- **Base:** `/api/v1` · **فرمت:** JSON (UTF-8) · **زبان پیام خطا:** فارسی · **نام فیلدها:** انگلیسی.
- **احراز هویت:** کوکی `mp_session` (opaque). جزئیات در `security.md`.
- **CSRF (اصلاح‌شده):** همهٔ متدهای unsafe (`POST/PUT/PATCH/DELETE`) روی نشست واردشده، هدر `X-CSRF-Token` با **توکن CSRF متصل به نشست** می‌خواهند (نه کوکی قابل‌خواندن — طراحی در `security.md §۲`). استثناها: login، register، reset-confirm (بدون نشست). download ها (GET) معاف‌اند.
- **Request ID:** هر پاسخ هدر `X-Request-ID` دارد؛ در پیام خطا بازتاب می‌شود.
- **Pagination:** `?page=1&page_size=50` (max 100) · پاسخ لیست: `{"data": [...], "meta": {"page", "page_size", "total_items", "total_pages"}}`.
- **Sorting:** `?sort=field` صعودی، `?sort=-field` نزولی؛ فقط whitelist هر endpoint.
- **Rate limit:** هدرهای `X-RateLimit-Remaining` و در 429: `Retry-After`.
- **OpenAPI:** `/api/v1/docs` در production غیرفعال یا محدود می‌شود.

### ۱.۵) Idempotency — طراحی کامل (مدل تراکنش واحد — اصلاحیهٔ نهایی P1)

| موضوع | تصمیم |
|---|---|
| ذخیره‌سازی | جدول `idempotency_keys` در مدل داده (§۵): tenant_id، user_id، key، operation، request_hash، response snapshot، expires_at — **بدون ستون وضعیت processing** |
| scope کلید | `UNIQUE (tenant_id, user_id, idempotency_key)` — کلید یک کاربر در یک tenant؛ بین کاربران/tenantها تداخلی ندارد |
| هش درخواست | SHA-256 از **method + path نرمال‌شده + operation + body کانونی‌شده** (JSON با مرتب‌سازی کلیدها)؛ تفاوت → `409 IDEMPOTENCY_CONFLICT` |
| جریان — گام ۱: رزرو اتمیک کلید | `BEGIN ISOLATION LEVEL READ COMMITTED` → `INSERT INTO idempotency_keys (tenant_id, user_id, idempotency_key, operation, request_hash, created_at, expires_at) VALUES (…, clock_timestamp(), clock_timestamp() + TTL) ON CONFLICT (tenant_id, user_id, idempotency_key) DO UPDATE SET operation = EXCLUDED.operation, request_hash = EXCLUDED.request_hash, response_status = NULL, response_body = NULL, created_at = clock_timestamp(), expires_at = clock_timestamp() + TTL WHERE idempotency_keys.expires_at <= clock_timestamp() RETURNING id` — اگر ردیف برگشت: این درخواست مالک کلید است (INSERT تازه یا **بازنشانی اتمیک رکورد منقضی**) |
| گام ۲ — مسیر مالک | اجرای عملیات + مقداردهی **هم‌زمانِ** `response_status` و `response_body` پیش از COMMIT (هر دو NULL یا هر دو مقدار — قاعدهٔ یکنواختی با CHECK در مدل داده) در **همان تراکنش** → COMMIT |
| گام ۳ — مسیر انتظار (RETURNING خالی) | رکورد زنده نزد تراکنش دیگری است. رفتار arbiter: INSERT تا پایان تراکنش مالک منتظر می‌ماند؛ سپس WHERE روی رکوردِ commit‌شده ارزیابی می‌شود: unexpired → skip بدون ردیف — و تراکنش **abort نمی‌شود** (برخلاف unique violation خام، `ON CONFLICT DO UPDATE WHERE` ناموفق فقط skip می‌کند) → `SELECT … FOR UPDATE` همان ردیف (فوری، رکورد committed) → مقایسهٔ `request_hash`: متفاوت → `409 IDEMPOTENCY_CONFLICT` (بدون اجرای عملیات)؛ یکسان → replay پاسخ ذخیره‌شده با هدر `Idempotent-Replayed: true` → `ROLLBACK` (فقط خوانده شده). اگر مالک **rollback** کرده باشد → ردیف هرگز دیده نمی‌شود → INSERT به‌صورت عادی موفق می‌شود → مسیر مالک (گام ۲) |
| شکست در میانهٔ تراکنش | خطا در عملیات مالک → کل تراکنش (شامل رکورد کلید) rollback → کلاینت می‌تواند با همان key retry کند |
| TTL و کلید منقضی | پس از ۲۴ ساعت (`IDEMPOTENCY_TTL_HOURS`) همان key برای **اجرای جدید** آزاد است؛ رکورد منقضی حتی پیش از پاک‌سازی مانع اجرا نیست — بازنشانی اتمیک در گام ۱ (`DO UPDATE … WHERE expires_at <= clock_timestamp()`)؛ rollback عملیات جدید، بازنشانی را هم rollback می‌کند و رکورد کهنهٔ منقضی باقی می‌ماند → retry دوباره ممکن |
| رقابت روی کلید منقضی | دو درخواست هم‌زمان با کلید منقضی: arbiter قید یکتایی آنها را سریال می‌کند — اولی WHERE برقرار → بازنشانی → مالک؛ دومی رکورد تازهٔ unexpired می‌بیند → WHERE نادرست → مسیر انتظار → پس از commit اولی، replay پاسخ جدید |
| زمان‌بندی (یافتهٔ ممیزی چهارم) | همهٔ نوشتن‌های زمانی (created_at و expires_at در رزرو و بازنشانی) و **شرط انقضا** با `clock_timestamp()` انجام می‌شود — ساعت واقعی DB در لحظهٔ اجرای statement. `now()` در این مسیر ممنوع است: زمان شروع تراکنش را برمی‌گرداند و تراکنشی که پشت قفل arbiter منتظر مانده، حتی پس از انقضای واقعی کلید، آن را «تازه» می‌بیند. TTL = اعتبار wall-clock از لحظهٔ رزرو/بازنشانی |
| مرز TTL با رقابت | تصمیم هر درخواست با `clock_timestamp()` لحظهٔ ارزیابی WHERE (پس از آزاد شدن قفل arbiter) گرفته می‌شود؛ arbiter درخواست‌ها را سریال می‌کند، پس در هر پنجرهٔ انقضا حداکثر یک درخواست جایگزین می‌کند. مثال: A در حال اجرا؛ کلید در میان انتظار منقضی می‌شود؛ B پس از commit A شرط را برقرار می‌بیند → بازنشانی و اجرا؛ C پشت قفل B → رکورد تازه → مسیر انتظار → replay پاسخ B. اگر B پیش از انقضا ارزیابی کرده باشد → B پاسخ A را replay می‌کند و C جایگزین/مالک می‌شود — تصمیم هر یک با ساعت واقعی خودش، سریال‌شده توسط arbiter |
| سطح Isolation | **READ COMMITTED الزامی** — middleware تراکنش را با `BEGIN ISOLATION LEVEL READ COMMITTED` آغاز می‌کند (و اگر پیش‌فرض نشست بالاتر باشد با `SET LOCAL` در همین تراکنش تحمیل می‌شود). چرا لازم است: (۱) در READ COMMITTED هر statement snapshot تازه می‌گیرد، پس `SELECT … FOR UPDATE` در گام ۳ پس از پایان مالک، ردیف committed تازه را می‌بیند؛ در REPEATABLE READ/SERIALIZABLE snapshot تراکنش ثابت است و همان SELECT به‌جای دیدن ردیف، خطای concurrent update می‌دهد؛ (۲) ارزیابی WHERE بازنشانیِ منقضی باید روی آخرین نسخهٔ committed با همین معنا انجام شود |
| رفتار Serialization Failure | اگر deployment سطح Isolation بالاتری تحمیل کند و گام ۱ یا ۳ با `SQLSTATE 40001 (serialization_failure)` شکست بخورد: middleware **کل تراکنش را از گام ۱ از نو** اجرا می‌کند (حداکثر ۳ بار با backoff تصادفی)؛ عدم موفقیت مجدد → `503` با خطای retriable — هرگز با تراکنش aborted ادامه نمی‌دهد. **این رفتار فقط طراحی است و روی PostgreSQL واقعی آزمایش نشده** |
| پاک‌سازی | حذف دوره‌ای رکوردهای منقضی با index(expires_at) — صرفاً بهداشت داده؛ صحت قرارداد به آن وابسته نیست (بازنشانی در مسیر arbiter انجام می‌شود) |
| مدل رزرو مستقل | در v1 عمداً انتخاب نشد (نیازمند وضعیت processing + بازیابی کلیدهای گیرکرده)؛ `IDEMPOTENCY_IN_PROGRESS` حذف شد — اگر آینده لازم شد، پروتکل رزرو مستقل مستند و پیاده می‌شود |
| عملیات الزامی v1 | `POST /imports/{id}/confirm` · `POST /reports` · `POST /comparison/runs` · `POST /sales/orders/{id}/returns` + `POST /sales/orders/{id}/refunds` — سایر POSTها اختیاری |

## ۲) طرح پاسخ خطای یکسان

```json
{
  "error": {
    "code": "PERMISSION_DENIED",
    "message": "شما اجازهٔ انجام این عملیات را ندارید.",
    "details": [ { "field": "role", "issue": "requires product:write" } ],
    "request_id": "b1c0…"
  }
}
```

| code | HTTP | توضیح |
|---|---|---|
| VALIDATION_ERROR | 400 | نقض قاعدهٔ تجاری |
| REQUEST_INVALID | 422 | اعتبارسنجی Pydantic با details فیلدها |
| AUTH_REQUIRED | 401 | بدون/با نشست نامعتبر |
| PERMISSION_DENIED | 403 | نقش/مجوز کافی نیست |
| NOT_FOUND | 404 | موجود نبود یا متعلق به tenant دیگر (بدون افشای وجود) |
| CONFLICT | 409 | نقض یکتایی/گذار نامعتبر |
| SOLE_OWNER_PROTECTED | 409 | حذف/تنزل تنها Owner ممنوع (security §۹) |
| IDEMPOTENCY_CONFLICT | 409 | همان key با درخواست متفاوت (method/path/operation/body) |
| REGISTRATION_CLOSED | 403 | ثبت‌نام با `ALLOW_REGISTRATION=false` بسته است |
| TENANT_SUSPENDED | 403 | tenant غیرفعال |
| RATE_LIMITED | 429 | عبور از سقف |
| UPLOAD_REJECTED | 400 | فایل نامعتبر (نوع/امضا/حجم/ساختار) |
| IMPORT_STATE_INVALID | 409 | گذار وضعیت import نامعتبر |
| CALCULATION_INPUT_INCOMPLETE | 422 | ورودی محاسبه ناقص + warnings |
| INTERNAL_ERROR | 500 | بدون جزئیات داخلی؛ فقط request_id |

## ۳) گروه‌های Endpoint — هر endpoint با مجوز صریح

فهرست کامل کدهای مجوز (۲۰ کد — `platform_admin` نقش سراسری است، نه کد مجوز) در `security.md §۴`؛ سازگاری یک‌به‌یک endpoint↔مجوز در §۶ همین سند کنترل شده است. «Session» = هر کاربر واردشده (فقط احراز هویت، بدون permission خاص).

### 3.1 auth

| Method | Path | مجوز | بدنه/پارامتر | نتیجه |
|---|---|---|---|---|
| POST | /auth/register | عمومی* | email, password, full_name, tenant_name | 201 — کاربر + tenant اول (Owner) |
| POST | /auth/login | عمومی | email, password | 200 + کوکی نشست + هدر `X-CSRF-Token` |
| POST | /auth/logout | Session | — | 204 — ابطال نشست جاری (نیازمند CSRF) |
| GET | /auth/me | Session | — | 200 — user، memberships، tenant فعال، permissions، `X-CSRF-Token` |
| POST | /auth/password/change | Session | current_password, new_password | 204 — ابطال سایر نشست‌ها |
| POST | /auth/password/reset-request | عمومی | email | 202 — پاسخ همیشه یکسان (بدون افشای وجود ایمیل) |
| POST | /auth/password/reset-confirm | عمومی | token, new_password | 204 — ابطال همهٔ نشست‌ها؛ توکن = random یک‌بارمصرف (بدون JWT) |
| GET | /auth/sessions | Session | — | 200 — نشست‌های فعال |
| DELETE | /auth/sessions/{id} | Session | — | 204 — ابطال نشست مشخص |

\* **سیاست ثبت‌نام (اصلاحیهٔ بازبینی):** دروازهٔ عمومی با کنترل سوءاستفاده — rate limit `RATE_LIMIT_REGISTER_PER_HOUR` (پیش‌فرض ۳/ساعت per-IP) · پرچم `ALLOW_REGISTRATION` (پیش‌فرض true؛ در production قابل بستن → `403 REGISTRATION_CLOSED`) · حداقل طول رمز ۸ · `tenant_name` → slug یکتا با blacklist کلمات رزرو (api، admin، www و…) · حداکثر ۵ tenant برای هر کاربر (`MAX_TENANTS_PER_USER`). **تأیید ایمیل در v1 وجود ندارد** (سرویس ایمیل در scope نیست) — محدودیت مستند + ریسک ثبت‌شده در گزارش بازبینی؛ جبران: rate limit سخت‌گیرانه + کنترل ادمین پلتفرم.

### 3.2 tenants و memberships

| Method | Path | مجوز | توضیح |
|---|---|---|---|
| POST | /tenants | Session | ساخت tenant (سقف MAX_TENANTS_PER_USER)؛ سازنده Owner |
| GET | /tenants | Session | tenantهای عضو کاربر |
| POST | /tenants/{id}/activate | عضو active | تنظیم tenant فعال در نشست (نیازمند CSRF؛ بازاعتبارسنجی membership در لحظه) |
| PATCH | /tenants/{id} | tenant:manage | نام/وضعیت |
| GET | /tenants/{id}/members | member:read | لیست اعضا |
| POST | /tenants/{id}/members | member:manage | افزودن عضو با ایمیل موجود + نقش (نقش owner فقط با انتقال مالکیت — خارج از v1) |
| PATCH | /tenants/{id}/members/{user_id} | member:manage | تغییر نقش — تنزل/حذف تنها Owner → `409 SOLE_OWNER_PROTECTED` |
| DELETE | /tenants/{id}/members/{user_id} | member:manage | لغو عضویت — همان قاعدهٔ Owner؛ اثر بر نشست‌ها: security §۹ |

### 3.3 users

| Method | Path | مجوز | توضیح |
|---|---|---|---|
| PATCH | /users/me | Session | ویرایش نام (تغییر ایمیل با تأیید، فاز بعد) |
| GET/PATCH | /admin/users/{id} | نقش platform_admin | غیرفعال‌سازی حساب — بیرون از دادهٔ tenant + Audit |

### 3.4 products و categories

| Method | Path | مجوز | توضیح |
|---|---|---|---|
| GET | /products | product:read | فیلترها: query، category_id، status، supplier (از طریق supplier_prices) |
| POST | /products | product:write | SKU یکتا در tenant (قواعد §۵ مدل داده) |
| GET | /products/{id} | product:read | |
| PATCH | /products/{id} | product:write | تغییر sale_price/purchase_cost → ردیف در `product_price_history` + Audit |
| POST | /products/{id}/purchase-cost-from-supplier-price | product:write | اقدام صریح برای تنظیم بهای خرید مرجع از یک supplier_price نهایی، هم‌ارز از نظر ارز و واحد؛ ثبت provenance و Audit در همان تراکنش |
| DELETE | /products/{id} | product:write | soft delete |
| GET | /products/{id}/price-history | product:read | از جدول `product_price_history` (change_type=purchase\|sale) |
| GET/POST | /categories · PATCH/DELETE /categories/{id} | product:read/write | درختی؛ یکتایی ریشه/زیردسته طبق مدل §۵ |
| POST | /products/{id}/variants | product:write | v1 حداقلی |

### 3.5 suppliers

| Method | Path | مجوز | توضیح |
|---|---|---|---|
| GET/POST | /suppliers | supplier:read/write | CRUD + فیلتر |
| PATCH/DELETE | /suppliers/{id} | supplier:write | DELETE = soft |
| POST | /suppliers/{id}/price-lists | supplier:write | ایجاد draft دستی با title، received_at و items[]؛ هر item شامل raw_name، sku?، product_id?، unit_price، currency و unit الزامی است |
| GET | /suppliers/{id}/price-lists | supplier:read | |
| GET | /price-lists/{id} | supplier:read | اقلام لیست |
| POST | /price-lists/{id}/finalize | supplier:write | نهایی‌سازی یک draft غیرخالی؛ پس از final تغییرناپذیر است |
| DELETE | /price-lists/{id} | supplier:write | حذف فقط draft؛ لیست نهایی حذف‌پذیر نیست |
| GET | /suppliers/{id}/price-history?product_id= | supplier:read | روند قیمت خرید از supplier_prices (ترتیب received_at لیست‌ها) |
| GET | /suppliers/lowest-price?product_id= | supplier:read | کمترین قیمت از لیست‌های final و ارز tenant؛ فقط ردیف‌های دارای product_id و unit برابر واحد محصول مقایسه می‌شوند؛ واحدهای دیگر در `excluded_units` گزارش می‌شوند |

### 3.6 sales

| Method | Path | مجوز | توضیح |
|---|---|---|---|
| GET/POST | /sales/orders | sales:read/write | فیلتر: date_from/to، status، payment_status، channel، query |
| GET | /sales/orders/{id} | sales:read | با اقلام |
| PATCH | /sales/orders/{id} | sales:write | ویرایش در وضعیت‌های مجاز (§۵) + Audit |
| POST | /sales/orders/{id}/status-transition | sales:write | {to} — فقط گذارهای §۵ |
| POST | /sales/orders/{id}/items | sales:write | افزودن قلم (snapshot قیمت/cost) |
| PATCH/DELETE | /sales/orders/{id}/items/{item_id} | sales:write | فقط پیش از completed |
| POST | /sales/orders/{id}/returns | sales:write | مرجوعی کامل/جزئی: [{sale_item_id, quantity, refund_amount}] — **Idempotency-Key اجباری**؛ رکورد جدید در `sales_returns` + `sales_return_items` (تغییرناپذیر) + به‌روزرسانی کش تجمعی sale_items در همان تراکنش + Audit |
| GET | /sales/orders/{id}/returns | sales:read | تاریخچهٔ مرجوعی‌های سفارش (سربرگ + اقلام) |
| POST | /sales/orders/{id}/refunds | sales:write | Create an immutable independent refund for a paid order cancelled before shipment; positive `amount` + optional `notes`; `Idempotency-Key` required; audit event; combined refund ceiling enforced. |
| GET | /sales/orders/{id}/refunds | sales:read | List independent refund records for the tenant-scoped order; does not include physical-return records. |
| GET | /sales/orders/{id}/profit | pricing:read | on-demand با موتور خالص + ثبت در ژورنال؛ پاسخ: تفکیک، `formula_version`، `calculation_id`، warnings |

### 3.7 expenses

| Method | Path | مجوز | توضیح |
|---|---|---|---|
| GET/POST | /expenses | expense:read/write | فیلتر: type، scope، date_from/to، order_id، product_id |
| PATCH | /expenses/{id} | expense:write | اصلاح کنترل‌شده + Audit |
| DELETE | /expenses/{id} | expense:write | حذف کنترل‌شده (soft + Audit) |
| GET | /expenses/breakdown?date_from&date_to | expense:read | تفکیک بر اساس نوع |

### 3.8 imports

| Method | Path | مجوز | توضیح |
|---|---|---|---|
| POST | /imports | import:execute | multipart: kind + file → بررسی نوع/امضا/حجم/ساختار → 201 با شیت‌ها، ستون‌ها، mapping پیشنهادی |
| PATCH | /imports/{id}/mapping | import:execute | mapping → اعتبارسنجی مجدد + preview (۲۰ ردیف + شمارش خطا/هشدار/تکراری) |
| GET | /imports/{id}/rows?status=error | import:read | خطاهای صفحه‌بندی‌شده |
| POST | /imports/{id}/confirm | import:execute | **Idempotency-Key اجباری**؛ فقط از `awaiting_confirmation` → commit اتمی ردیف‌های valid + گزارش |
| GET | /imports · /imports/{id} | import:read | تاریخچه/جزئیات با عنوان لیست، تأمین‌کننده و قیمت/واحد هر طرف |
| GET | /imports/{id}/error-report.xlsx | import:read | دانلود خطاها — مجوز import:read + scope tenant + فقط importهای همان tenant (security §۹) |
| DELETE | /imports/{id} | import:execute | فقط pre-commit |

### 3.9 pricing

| Method | Path | مجوز | توضیح |
|---|---|---|---|
| POST | /pricing/suggest | pricing:read | {product_id یا cost، target_margin، include_fees؟} → قیمت پیشنهادی + تفکیک (FV-2) |

### 3.10 comparison

| Method | Path | مجوز | توضیح |
|---|---|---|---|
| POST | /comparison/runs | **comparison:write** | {base_list_id, target_list_id, match_strategy} + **Idempotency-Key اجباری** — ایجاد، عملیات سازنده است (اصلاحیهٔ نهایی: از comparison:read تغییر کرد) |
| GET | /comparison/runs · /comparison/runs/{id} | comparison:read | تاریخچه/جزئیات |
| POST | /comparison/runs/{id}/confirm-matches | **comparison:write** | تأیید/رد تطبیق‌های نامطمئن و اتصال به product (مجوز اختصاصی — اصلاحیهٔ ناهماهنگی supplier:write) |

### 3.11 analytics

| Method | Path | مجوز | توضیح |
|---|---|---|---|
| GET | /analytics/summary | analytics:read | Revenue/Cost/Gross/Net/Margin + بازه |
| GET | /analytics/products | analytics:read | سودآورترین/زیان‌ده‌ترین (اقلام cost-unknown جدا گزارش می‌شوند) |
| GET | /analytics/trends | analytics:read | روند با group_by=day\|month |
| GET | /analytics/expenses | analytics:read | تفکیک هزینه‌ها |

> همهٔ اعداد analytics فقط از موتور `pricing` می‌آیند (قرارداد معماری §۵).

### 3.12 reports

| Method | Path | مجوز | توضیح |
|---|---|---|---|
| POST | /reports | report:generate | {type, format, params} + **Idempotency-Key اجباری** → 201 |
| GET | /reports · /reports/{id} | report:read | لیست/جزئیات |
| GET | /reports/{id}/download | report:read | دانلود مستقیم از API (بدون URL عمومی) — فقط reportهای completedِ همان tenant (security §۹) |

### 3.13 settings و health

| Method | Path | مجوز | توضیح |
|---|---|---|---|
| GET | /settings | Session | تنظیمات tenant |
| PATCH | /settings | settings:write | ویرایش + Audit |
| GET | /healthz · /readyz | عمومی | healthcheck (بدون اطلاعات حساس) |

## ۴) قواعد کد HTTP

200 خواندن/به‌روزرسانی · 201 ساخت · 202 reset-request · 204 بدون بدنه · 400 قاعدهٔ تجاری · 422 schema · 401/403/404/409 طبق §۲ · 413 حجم · 415 نوع · 429 rate limit · 500 فقط خطای واقعی سرور.

## ۵) گذارهای وضعیت — دقیق و کامل

**sales_orders (`order_status`):** `pending` -> `confirmed`; `pending` -> `cancelled`; `confirmed` -> `processing`; `confirmed` -> `cancelled`; `processing` -> `completed`; `processing` -> `cancelled`; `completed` and `cancelled` are terminal. Cancellation is rejected after shipment. **`payment_status`:** `unpaid` -> `paid` is an explicit receipt confirmation; `paid` -> `partially_refunded`/`refunded` is derived from committed physical-return refunds and independent refunds. In v1, `paid` means the full net order amount was received; partial payments are out of scope. **`shipping_status`:** `not_shipped` -> `shipped` -> `delivered`; fully returned shipped/delivered orders become `returned`. Physical returns require shipped/delivered status; independent refunds require a cancelled paid order.

**imports (`import_status`):** `uploaded`→`parsed`→`mapped`→`validated`→`awaiting_confirmation`→`committed` · هر مرحلهٔ pre-commit → `failed` (خطای ساختاری) یا `cancelled` (کاربر) · `committed`/`failed`/`cancelled` پایانی · commit فقط از `awaiting_confirmation`؛ گذار نامعتبر → `409 IMPORT_STATE_INVALID`.

## ۶) سازگاری API ↔ RBAC (نتیجهٔ کنترل اصلاحی)

- فهرست مجوزها (۲۰ کد): `product:read/write` · `supplier:read/write` · `sales:read/write` · `expense:read/write` · `import:read/execute` · `pricing:read` · `analytics:read` · `report:read/generate` · `comparison:read/write` · `member:read/manage` · `tenant:manage` · `settings:write` — به‌اضافهٔ نقش سراسری `platform_admin`.
- هر endpoint جدول §۳ دارای ستون مجوز صریح است؛ هر مجوزِ استفاده‌شده در ماتریس RBAC (security §۴) تعریف شده است — **کد بدون مجوز و مجوز بدون endpoint وجود ندارد** (کنترل خودکار این سازگاری در CI از Phase 3: مقایسهٔ decoratorها با ماتریس).
- اصلاح انجام‌شده (دور دوم): ایجاد مقایسه (`POST /comparison/runs`) به `comparison:write` منتقل شد — مشاهدهٔ نتایج با `comparison:read` می‌ماند و تأیید تطبیق‌ها نیز `comparison:write` است؛ افزودن `member:read` برای GET members؛ تأیید تطبیق‌ها از `supplier:write` به `comparison:write`.
- **پیامد نقش‌ها:** Analyst فقط `comparison:read` دارد → در v1 نمی‌تواند اجرای مقایسه بسازد یا تطبیق‌ها را تأیید کند (فقط owner/admin). این تصمیم صریحاً در ماتریس RBAC (security §۴) ثبت شده است؛ در بازبینی بعدی قابل بازنگری است.

## ۷) سازگاری با Frontend

- Frontend هیچ منطق مالی را تکرار نمی‌کند؛ همهٔ اعداد از API (با `formula_version`).
- توکن CSRF در پاسخ login/me از هدر `X-CSRF-Token` خوانده و فقط در حافظهٔ برنامه نگه داشته می‌شود (کوکی CSRF وجود ندارد).
- نمایش اعداد با Intl (fa-IR) و واحد پول tenant؛ ذخیرهٔ دادهٔ حساس در مرورگر ممنوع.
- TypeScript types از OpenAPI — اتصال در Phase بعد از طراحی frontend.

#### Phase 4 Step 3 implemented import contract

All paths above are prefixed with `/api/v1`. `POST /imports` is `multipart/form-data`: `kind=products|supplier_prices`, `file`, optional XLSX `sheet_name`; supplier-price imports additionally require `supplier_id` and accept `price_list_title` and `received_at`. `sales` remains reserved and returns `422 IMPORT_KIND_NOT_READY`.

Product mappings: `sku`, `name`, `unit` (required); `description`, `sale_price`, `purchase_cost`, `is_active` (optional). Supplier-price mappings: `raw_name`, `unit_price`, `unit` (required); `sku`, `currency` (optional). Mapping values must reference unique, exact headers returned by upload. Confirmation commits valid rows only and reports skipped error/duplicate rows. Supplier-price confirmation creates a **draft** price list; a separate explicit finalize action is required.

`POST /imports/{id}/confirm` requires a 1–255 character `Idempotency-Key`. The stored result is scoped by tenant and user; a repeated identical request replays the original response. Reusing the key for a different operation/path returns 409. Confirmation, domain writes, price history, audit and idempotency result share one transaction.


#### Phase 4 Step 4 comparison behavior

`POST /comparison/runs` accepts `sku`, `normalized_name`, or `sku_then_name`; it requires an `Idempotency-Key` and compares only distinct final lists in the active tenant. `GET /comparison/runs` and `GET /comparison/runs/{id}` require `comparison:read`. `POST /comparison/runs/{id}/confirm-matches` requires `comparison:write`; confirm decisions require an active `product_id`, and ambiguous one-sided rows additionally require `peer_price_id` from the opposite list. The server validates tenant, list side, unit equality and existing product links before atomically linking both price rows.
