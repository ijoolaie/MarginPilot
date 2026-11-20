# تصمیم‌های معماری (ADR) — MarginPilot Phase 1

فرمت هر ADR: زمینه / تصمیم / دلیل / گزینه‌های جایگزین / هزینهٔ تغییر در آینده.

## ADR-001 — معماری Modular Monolith
- **تصمیم:** یک اپلیکیشن FastAPI با ماژول‌های دارای مرز import سخت‌گیرانه؛ تک‌ریپو با backend/ و frontend/.
- **دلیل:** سادگی استقرار (docker compose)، تراکنش یکپارچه روی PostgreSQL، سرعت توسعهٔ MVP، عدم پیچیدگی شبکه.
- **جایگزین‌ها:** Microservices (رد: هزینهٔ عملیاتی و پیچیدگی برای تیم/مقیاس فعلی — و منع صریح نسخهٔ اول)؛ Django monolith (رد: ترجیح FastAPI/Pydantic v2 و ساختار ماژول صریح).
- **هزینهٔ تغییر در آینده:** متوسط — با قوانین §۵ architecture.md و import-linter، استخراج یک ماژول به سرویس جدا بدون بازنویسی دامنه ممکن است.

## ADR-002 — Backend: FastAPI + SQLAlchemy 2 + Alembic + PostgreSQL 16
- **دلیل:** اعتبارسنجی خودکار با Pydantic v2، OpenAPI خودکار، async در دسترس، اکوسیستم پایدار.
- **جایگزین‌ها:** Django REST (رد: اضافه‌بار برای API محض)، Flask (رد: ابزارسازی بیشتر برای validation/migration).
- **هزینهٔ تغییر:** بالا — انتخاب بلندمدت؛ کاهش ریسک با جداسازی Domain از Framework.

## ADR-003 — احراز هویت: Opaque Session Cookie ذخیره در PostgreSQL (تصمیم تأییدشدهٔ شما)
- **دلیل:** ابطال فوری (خروج/تغییر رمز/غیرفعال‌سازی)، ذخیرهٔ هش توکن (نه توکن)، امن‌تر از JWT در localStorage مقابل XSS، سادگی same-origin.
- **جایگزین‌ها:** JWT stateless (رد: ابطال دشوار و نیاز به blacklist که همان DB می‌شود)، JWT+refresh rotation (پیچیدگی بیشتر با همان نیاز DB).
- **به‌روزرسانی بازبینی Phase 1:** بازیابی رمز با توکن تصادفی یک‌بارمصرف و هش در DB انجام می‌شود — **JWT به‌طور کامل از v1 حذف شد** (PyJWT از وابستگی‌ها خارج شد)؛ توکن CSRF نیز متصل به نشست است (ADR-020).
- **هزینهٔ تغییر:** متوسط — مرز نشست در `identity/service` ایزوله است؛ مقیاس‌پذیری بعدی با Redis-backed session store بدون تغییر API.

## ADR-004 — Multi-tenancy: Shared schema + tenant_id با scoping اجباری
- **دلیل:** سادگی migration و joinها، کافی برای مقیاس SMB بازار هدف، تست IDOR به‌عنوان ایمنی.
- **جایگزین‌ها:** schema-per-tenant (رد برای v1: هزینهٔ migration/مدیریت صدها schema؛ Migrations پیچیده)، db-per-tenant (رد: عملیات بکاپ/ارتقا گران).
- **هزینهٔ تغییر:** بالا — اگر مشتری enterprise با الزام جداسازی فیزیکی بیاید، نیاز به پروژهٔ جداسازی داده دارد؛ ریسک با تست IDOR خودکار و Repository scoping مهار شده.

## ADR-005 — پول: Decimal + NUMERIC(20,2)، minor_units=0 برای IRT/IRR، بدون تبدیل ضمنی (تأییدشده)
- **جایگزین‌ها:** integer minor units (رد: تومان/ریال واحد خرد عملی ندارند و اعشار ورودی‌ها را دور می‌ریزد)، float (ممنوع — عدم قطعیت).
- **هزینهٔ تغییر:** بالا برای مدل ذخیره، پایین برای قواعد — تبدیل صریح آینده (مثلاً نمایش ریال) فقط در لایهٔ نمایش.

## ADR-006 — گرد کردن: HALF_UP در نقاط تعریف‌شده + largest-remainder برای تخصیص (تأییدشده)
- **دلیل:** قابل پیش‌بینی برای کاربر ایرانی (مطابق عرف حسابداری)، جمع‌های سازگار (بدون drift چند ریالی)، بردار مرجع تست‌پذیر.
- **جایگزین‌ها:** banker's rounding (رد: غیرشهودی برای کاربر نهایی)، گرد کردن در هر مرحلهٔ میانی (رد: drift انباشته).
- **هزینهٔ تغییر:** کم — همهٔ گرد کردن از یک نقطهٔ `core.money` می‌گذرد و formula_version تغییر می‌کند.

## ADR-007 — موتور محاسبه: توابع خالص + ژورنال calculations + formula_version
- **دلیل:** صحت و بازتولیدپذیری گزارش، تست صددرصدی بدون DB، تفکیک قواعد از منبع داده.
- **جایگزین‌ها:** aggregation در SQL (رد: قوانین پیچیدهٔ مرجوعی/تخصیص غیرقابل تست و ناسازگار بین گزارش‌ها)، محاسبه در Frontend (منع صریح).
- **هزینهٔ تغییر:** کم — نسخه‌بندی فرمول، تغییرات گذشته را از دادهٔ تاریخچه جدا می‌کند.

## ADR-008 — Import: state machine دو مرحله‌ای (validate → preview → confirm)
- **دلیل:** هیچ دادهٔ ناسالم وارد DB نمی‌شود؛ کاربر دید و کنترل دارد؛ خطاها قابل دانلود و ردیف‌های valid قابل commit انتخابی.
- **جایگزین‌ها:** import مستقیم (رد: خطر دادهٔ کثیف در سوابق مالی)، صف async با Celery (رد در v1: پیچیدگی؛ مدل برای انتقال آماده است).
- **هزینهٔ تغییر:** کم — commit از طریق سرویس‌های ماژول مقصد است؛ افزودن ورکر پس‌زمینه لایهٔ state را تغییر نمی‌دهد.

## ADR-009 — RBAC: نقش‌ها و مجوزها در DB، اعمال فقط سمت Backend
- **دلیل:** توسعه‌پذیری (نقش سفارشی آینده)، جلوگیری از امنیت نمایشی، Audit ساده.
- **جایگزین‌ها:** نقش‌های هاردکد (رد: انعطاف ناکافی)، Casbin/policy engine خارجی (رد: پیچیدگی غیرضروری v1).
- **هزینهٔ تغییر:** کم.

## ADR-010 — Rate limiting درون‌حافظه‌ای در v1 (Redis-ready)
- **دلیل:** تک‌instance v1؛ Redis فقط با اثبات نیاز اضافه می‌شود (اصل Master Prompt).
- **جایگزین‌ها:** slowapi (همان in-memory است؛ وابستگی اضافه نمی‌گیریم)، Redis اکنون (رد: نیاز اثبات‌نشده).
- **هزینهٔ تغییر:** کم — interface rate limiter به‌گونه‌ای طراحی می‌شود که backend store عوض‌شدنی باشد.

## ADR-011 — Frontend: React SPA (Vite) same-origin پشت Caddy، بدون SSR
- **دلیل:** داشبورد data-heavy؛ استقرار ساده (static + reverse proxy)؛ RTL با Tailwind logical properties؛ فونت وزیرمتن self-host.
- **جایگزین‌ها:** Next.js/SSR (رد: پیچیدگی استقرار بی‌دلیل برای پنل لاگین‌دار + منع fullstack در محیط جاری)، Vue (انتخاب تیمی؛ React اکوسیستم تست قوی‌تر prompt‌محور).
- **هزینهٔ تغییر:** بالا — انتخاب بلندمدت frontend.

## ADR-012 — پردازش داده: Pandas در v1 (تأییدشده؛ Polars اضافه نمی‌شود)
- **دلیل:** نصب و پایدار، کافی برای سقف ۱۰۰هزار ردیف، آشنایی بالا.
- **جایگزین‌ها:** Polars (سرعت بیشتر؛ در صورت نیاز آینده فقط داخل ماژول imports جایگزین می‌شود — مرز ایزوله).
- **هزینهٔ تغییر:** کم.

## ADR-013 — Billing: حذف از ساختار v1 (به‌روزرسانی بازبینی)
- **تصمیم اولیه:** Adapter interface برای پرداخت آینده. **تصمیم نهایی بازبینی:** billing در v1 هیچ مصرف‌کننده‌ای ندارد → پوشه و interface از اسکلت حذف شد؛ scope آینده فقط مستند می‌ماند (data-model §۹).
- **دلیل:** اصل «هیچ فایل/Abstraction بدون مصرف‌کننده» (شرط D + بازبینی P2).
- **هزینهٔ بازگشت:** کم — وقتی پرداخت واقعاً وارد scope شد، ماژول تازه با همان مرزهای معماری ساخته می‌شود؛ هیچ سرویس موجودی به آن وابسته نیست.

## ADR-014 — شناسه‌ها: bigint identity برای دامنه، UUID فقط برای sessions
- **دلیل:** join و ایندکس سریع و خوانا؛ UUID تصادفی فقط جایی که نشت‌پذیری مهم است (نشست).
- **جایگزین‌ها:** UUID v7 همه‌جا (رد برای v1: حجم ایندکس/خوانایی برای مقیاس فعلی).
- **هزینهٔ تغییر:** بالا بعد از دادهٔ واقعی — تصمیم در همین نقطه قفل می‌شود.

## ADR-015 — تست Integration: CI-first با PostgreSQL واقعی (تأییدشدهٔ شما)
- **دلیل:** محدودیت سندباکس (بدون Docker/PG)؛ شروط شما: mock جایگزین integration نیست + اجرای محلی بخش پذیرش است.
- **جایگزین‌ها:** SQLite برای تست (رد: تفاوت رفتار NUMERIC/constraint/integrity)، embedded-postgres (پلن B آزمایشی در Phase 3).
- **هزینهٔ تغییر:** کم.

## ADR-016 — زبان‌ها: کد/API انگلیسی، UI فارسی RTL، مستندات فارسی (تأییدشده)
- **دلیل:** استاندارد صنعتی برای کد و API؛ تجربهٔ کاربر فارسی‌زبان.
- **هزینهٔ تغییر:** ناچیز.

## ADR-017 — سیاست نسخه‌ها: pin محافظه‌کارانه + ماتریس سازگاری قبل از انتخاب (تأییدشده)
- **دلیل:** شرط ۶ شما؛ نسخه‌های خیلی جدید (TypeScript 7، Zod 4) ریسک ناسازگاری اکوسیستم دارند.
- **اجرای واقعی:** در Phase 2 ماتریس سازگاری چک و نسخه‌های آزمایش‌شده در `dependencies.md` ثبت می‌شود؛ بدون ثبت سازگاری، pin انجام نمی‌شود. (بازبینی: ماتریس باید با نصب و build آزمایشی واقعی اجرا شود، نه فقط استعلام registry.)
- **هزینهٔ تغییر:** کم (lock file).

## ADR-018 — جداسازی tenant در سطح دیتابیس با FK مرکب (اصلاحیهٔ بازبینی P0)
- **تصمیم:** همهٔ روابط بین رکوردهای tenant-owned با FK مرکب `(tenant_id, parent_id)` به `UNIQUE (tenant_id, id)` والد تعریف می‌شوند (۲۴ FK — data-model §۴؛ شامل FK سه‌ستونهٔ variant و جداول مرجوعی)؛ فیلتر کد به‌تنهایی کافی نیست.
- **دلیل:** PostgreSQL خودش ارجاع متقاطع بین tenantها را رد می‌کند؛ حفرهٔ «order_id از tenant دیگر» ساختاراً بسته می‌شود.
- **جایگزین‌ها:** فقط فیلتر Repository (رد: بازبینی ناقص بودنش را نشان داد)، Row-Level Security در PostgreSQL (گزینهٔ سخت‌سازی آینده؛ v1 ساده نگه داشته شد)، Trigger (رد در v1: سادگی و دیباگ‌پذیری).
- **هزینهٔ تغییر:** بالا بعد از دادهٔ واقعی (migration سنگین) — به همین دلیل در Phase 3 از ابتدا اعمال می‌شود.

## ADR-019 — مدل یکپارچهٔ تخفیف/Revenue (اصلاحیهٔ بازبینی P0) — FV-2
- **تصمیم:** تخفیف فقط یک‌بار داخل Net Line Revenue اعمال می‌شود؛ فرمول Net Operating Profit هیچ جملهٔ تخفیفی ندارد؛ مرجوعی با return_variance علامت‌دار و RETURN_LOSS همیشه مثبت تعریف شد.
- **دلیل:** رفع شمارش دوگانهٔ تخفیف و ابهام علامت در نسخهٔ قبلی (یافتهٔ بازبینی).
- **جایگزین‌ها:** ذخیرهٔ revenue درشت + کسر تخفیف در فرمول net (رد: دو منبع حقیقت و خطای انسانی در هر گزارش).
- **هزینهٔ تغییر:** کم — FV-1 باطل و FV-2 مستند شد؛ نسخه‌بندی فرمول همین سناریو را مدیریت می‌کند.

## ADR-020 — CSRF: توکن متصل به نشست (اصلاحیهٔ بازبینی P1)
- **تصمیم:** توکن CSRF تصادفی per-session، هش در `sessions.csrf_token_hash`، تحویل با هدر پاسخ `X-CSRF-Token`، ارسال دوباره در هدر درخواست؛ بدون کوکی CSRF.
- **دلیل:** double-submit ساده در برابر Cookie Injection (subdomain مصحوح) مقاوم نیست؛ توکن متصل به نشست قابل جعل نیست.
- **جایگزین‌ها:** double-submit امضاشده (HMAC کوکی+نشست — معمول ولی پیچیده‌تر)، synchronizer token سرور-محور کلاسیک (همان انتخاب ما — session-bound).
- **هزینهٔ تغییر:** کم — middleware CSRF ایزوله است.

## ADR-021 — Idempotency: ذخیره‌سازی DB با `idempotency_keys` (اصلاحیهٔ بازبینی P1)
- **تصمیم:** جدول idempotency_keys با scope `(tenant_id, user_id, key)`، هش درخواست کامل (method + path نرمال‌شده + operation + body کانونی‌شده — تعریف دقیق در ADR-023)، snapshot پاسخ nullable با قاعدهٔ یکنواختی (`response_status`/`response_body`: در رزرو هر دو NULL، پس از موفقیت هر دو با هم، در بازنشانی هر دو NULL — CHECK در مدل داده)، انقضای ۲۴ ساعت با زمان واقعی statement (`clock_timestamp()` در نوشتن و ارزیابی — نه `now()` زمانِ شروعِ تراکنش)؛ رزرو اتمیک با `ON CONFLICT` درون تراکنش واحد READ COMMITTED؛ شکست → rollback کلید؛ عملیات الزامی: import confirm، گزارش، مقایسه، مرجوعی.
- **دلیل:** قرارداد Idempotency-Key بدون مدل ذخیره‌سازی صرفاً متنی بود (یافتهٔ بازبینی).
- **جایگزین‌ها:** Redis (رد در v1 — بدون Redis)، نگهداری در حافظه (رد: ری‌استارت/چند-instance).
- **هزینهٔ تغییر:** کم — جدول مستقل؛ انتقال به Redis بعداً فقط store را عوض می‌کند.

## ADR-022 — مرجوعی به‌عنوان موجودیت درجه‌یک (اصلاحیهٔ نهایی P0)
- **تصمیم:** جدول‌های `sales_returns` (سربرگ: سفارش، تاریخ، کاربر، وضعیت، متادیتای بازپرداخت) و `sales_return_items` (قلم، مقدار، مبلغ بازپرداخت، snapshot) با FKهای مرکب tenant-aware؛ فیلدهای تجمعی `sale_items` فقط کشِ مشتق‌شده‌اند (منبع حقیقت: sales_return_items)؛ رکوردهای مرجوعی در v1 تغییرناپذیرند (اصلاح = سند جبرانی آینده).
- **دلیل:** ممیزی‌پذیری چند مرجوعی مستقل یک قلم، زمان/کاربر/وضعیت هر بازپرداخت، و بازتولید تاریخی دقیق (یافتهٔ بازبینی نهایی).
- **جایگزین‌ها:** فقط فیلدهای تجمعی در sale_items (رد: عدم ممیزی‌پذیری و دشواری اصلاح).
- **هزینهٔ تغییر:** کم — جدول‌های جدید مستقل؛ محاسبات مالی تغییری در فرمول‌ها نداشت.

## ADR-023 — Idempotency: مدل تراکنش واحد با رزرو اتمیک (اصلاحیهٔ نهایی P1 — بازنگری دور پنجم)
- **تصمیم:** رزرو کلید با یک statement در تراکنش **READ COMMITTED**: `INSERT … ON CONFLICT (tenant_id, user_id, idempotency_key) DO UPDATE SET operation = EXCLUDED.operation, request_hash = EXCLUDED.request_hash, response_status = NULL, response_body = NULL, created_at = clock_timestamp(), expires_at = clock_timestamp() + TTL WHERE idempotency_keys.expires_at <= clock_timestamp() RETURNING id`. ردیف در RETURNING → مالک کلید (INSERT تازه یا بازنشانی اتمیک رکورد منقضی) → عملیات + مقداردهی هم‌زمانِ پاسخ در همان تراکنش → COMMIT. RETURNING خالی → رکورد زندهٔ دیگری وجود دارد؛ arbiter تا پایان تراکنش مالک منتظر می‌ماند و چون skip با ON CONFLICT تراکنش را abort **نمی‌کند** (برخلاف unique violation خام)، همان تراکنش با `SELECT … FOR UPDATE` رکورد committed را می‌خواند: hash متفاوت → `IDEMPOTENCY_CONFLICT`؛ یکسان → replay؛ سپس ROLLBACK. اگر مالک rollback کرده باشد، INSERT عادی موفق → مسیر مالک. **زمان‌ها:** همهٔ نوشتن‌های زمانی و شرط انقضا با `clock_timestamp()` (ساعت واقعی DB در لحظهٔ statement) — `now()` در این مسیر ممنوع است چون هنگام انتظار پشت قفل، کلید واقعاً منقضی را تازه نشان می‌دهد (یافتهٔ ممیزی چهارم). `IDEMPOTENCY_IN_PROGRESS` حذف؛ request_hash = method + path نرمال‌شده + operation + body کانونی‌شده.
- **دلیل:** دور سوم: «خطای یکتایی سپس ادامهٔ همان تراکنش» از نظر PostgreSQL نادرست بود؛ دور پنجم: `now()` برای ارزیابی TTL نادرست بود — تراکنش منتظر پشت قفل، پس از انقضای واقعی کلید آن را تازه می‌بیند. **READ COMMITTED ساختاری لازم است:** در آن هر statement snapshot تازه می‌گیرد و `SELECT FOR UPDATE` پس از پایان مالک ردیف را می‌بیند؛ در REPEATABLE READ/SERIALIZABLE همین SELECT به‌جای دیدن ردیف، serialization failure (`SQLSTATE 40001`) می‌دهد → در آن صورت middleware کل تراکنش را از گام ۱ (حداکثر ۳ بار با backoff تصادفی) retry می‌کند و در نهایت `503` retriable می‌دهد. **این رفتار فقط طراحی است و روی PostgreSQL واقعی آزمایش نشده.**
- **جایگزین‌ها:** SAVEPOINT دور unique violation خام (رد)، `SELECT FOR UPDATE` قبل از INSERT (رد)، ارزیابی TTL با ساعت اپلیکیشن (رد: WHERE باید در همان statement arbiter اجرا شود و منبع حقیقت زمان DB باشد؛ drift ساعت اپلیکیشن ریسک دارد)، `statement_timestamp()` (رد: در statementهای بعدی مسیر مالک معنای ناهمگون می‌سازد)، مدل رزرو مستقل (همچنان رد برای v1).
- **هزینهٔ تغییر:** کم — middleware Idempotency ایزوله است.

## ADR-024 — یکپارچگی ساختاری در سطح DB: FK سه‌ستونه و حذف supplier_id (اصلاحیهٔ نهایی P0/P1)
- **تصمیم:** (۱) `sale_items.variant_id` با FK سه‌ستونه `(tenant_id, product_id, variant_id)` به `UNIQUE (tenant_id, product_id, id)` روی product_variants — تعلق variant به همان product در DB تضمین می‌شود نه فقط سرویس؛ (۲) ستون `supplier_prices.supplier_id` حذف شد — تأمین‌کننده از طریق `supplier_price_lists` استخراج می‌شود.
- **دلیل:** کنترل سرویس به‌تنهایی انتخاب مطلوبی نیست (بازبینی نهایی)؛ حذف ستون تکراری «یک منبع حقیقت» می‌سازد.
- **جایگزین‌ها:** trigger همگام‌سازی (رد در v1)، نگهداری supplier_id با قید مرکب همگام‌ساز (رد: پیچیده‌تر و شکننده‌تر از استخراج).
- **هزینهٔ تغییر:** کم.


## ADR-025 — تمرکز بر تحویل Mini-SaaS MVP و فازبندی فشرده (مصوب 2026-11-20)
- **زمینه:** پس از تکمیل زیرساخت، هویت/tenancy، کاتالوگ، Import و Backend مقایسه، بخش‌های اصلی ارزش محصول (فروش/هزینه، محاسبهٔ سود، UI و گزارش) باقی مانده‌اند. ادامهٔ خردکردن کار به تعداد زیادی فاز مستقل، زمان تحویل MVP را زیاد می‌کند بدون آنکه ارزش کاربر را به همان نسبت افزایش دهد.
- **تصمیم:** ادامهٔ پروژه در چهار بستهٔ تحویل محصولی انجام می‌شود: Phase 5 Sales & Expenses؛ Phase 6 Financial Calculation Engine؛ Phase 7 MVP UI, Dashboard & Reports؛ Phase 8 Release Readiness. جزئیات و معیار پذیرش در `docs/mvp-roadmap.md` مرجع است.
- **اصل دامنه:** فقط قابلیت‌های لازم برای جریان کامل MVP پیاده می‌شوند. Microservices، صف توزیع‌شدهٔ پیچیده، حسابداری کامل، انبارداری جامع، گزارش‌ساز سفارشی، AI مالی، اپ موبایل و مقیاس سازمانی تا اثبات نیاز به تعویق می‌افتند.
- **الزامات غیرقابل‌مصالحه:** tenant isolation، RBAC، امنیت نشست و upload، Decimal/NUMERIC، صحت و نسخه‌بندی فرمول مالی، PostgreSQL integration tests، CI/security scans و backup/restore آزموده‌شده.
- **دلیل:** تحویل زودتر ارزش واقعی با حفظ کنترل ریسک‌های مالی و امنیتی؛ معماری Modular Monolith و PostgreSQL فعلی برای MVP کافی‌اند.
- **هزینهٔ تغییر:** کم تا متوسط؛ فازبندی تحویل است و مانع افزودن قابلیت‌های اثبات‌شده در نسخه‌های بعد نمی‌شود.


## ADR-026 — سفارش فروش سند مالی است و soft-delete ندارد (Phase 5)
- **زمینه:** جدول `sales_orders` در نسخهٔ قبلی هم `deleted_at` و unique index جزئی داشت، اما اصل §۱ مدل داده soft-delete را فقط برای کاتالوگ مجاز می‌دانست و برای سوابق مالی ابطال با وضعیت + Audit را تعیین می‌کرد. قرارداد API نیز برای سفارش DELETE تعریف نکرده و گذار به `cancelled` را مسیر ابطال قرار داده است.
- **تصمیم:** سفارش فروش soft-delete نمی‌شود و `deleted_at` ندارد؛ شمارهٔ سفارش در هر tenant همواره یکتا است (`UNIQUE (tenant_id, order_number)`). ابطال فقط با transition مجاز به `cancelled` و ثبت Audit انجام می‌شود. `sale_items` و اسناد مرجوعی نیز حذف‌پذیر نیستند؛ هزینه‌ها طبق قرارداد خود soft-delete کنترل‌شده دارند.
- **دلیل:** حفظ سابقهٔ مالی و جلوگیری از آزادشدن/استفادهٔ مجدد شمارهٔ سفارش پس از ابطال؛ هم‌راستایی اصل حذف و قرارداد API.
- **هزینهٔ تغییر:** کم؛ حذف یک ستون و تبدیل partial unique به unique در migration اولیهٔ دامنه، پیش از انتشار و بدون دادهٔ production.


## ADR-027 — تخصیص متناسب تخفیف سفارش بر مبنای ارزش خالص هر قلم (Phase 5)
- **زمینه:** قرارداد محاسبات، تخصیص تخفیف سطح سفارش با largest-remainder را الزامی کرده بود، اما مبنای تناسب و قاعدهٔ تساوی به‌صراحت تعیین نشده بود.
- **تصمیم:** برای هر قلم ابتدا (B_i = quantity_i \times unit\_price_i - line\_discount_i) محاسبه می‌شود. تخفیف سفارش متناسب با (B_i / \sum B) بین اقلام تقسیم می‌شود. سهم‌ها به quantum پولی (در v1 برای IRT/IRR یک واحد کامل) تبدیل می‌شوند: کف سهم خام تخصیص می‌یابد و واحدهای باقیمانده بر اساس بزرگ‌ترین بخش کسری توزیع می‌شوند؛ تساوی با ترتیب اصلی اقلام شکسته می‌شود. مجموع سهم‌ها باید دقیقاً برابر تخفیف سفارش باشد. مبنای صفر همراه تخفیف صفر، سهم‌های صفر می‌دهد؛ تخفیف مثبت روی مبنای صفر یا تخفیف بیش از مجموع مبنا رد می‌شود.
- **دلیل:** تخصیص قابل‌بازتولید، بدون شناوری یا خطای جمع، متناسب با ارزش واقعی هر قلم پس از تخفیف خطی؛ ترتیب سطر tie-breaker ساده و قطعی است.
- **جایگزین‌ها:** تقسیم مساوی، تقسیم بر اساس مبلغ قبل از تخفیف خطی، و گرد کردن مستقل هر سهم (رد: ناعادلانه یا مستعد اختلاف جمع).
- **هزینهٔ تغییر:** کم؛ الگوریتم خالص Decimal است و با تغییر داده‌های محصول/تأمین‌کننده وابستگی ندارد.

## ADR-028 - Separate cancellation refunds from physical returns
- **Decision:** Cancellation, cash refund and physical goods return are separate events. `sales_refunds` is an immutable ledger for independent refunds on paid orders cancelled before shipment. `sales_returns` and `sales_return_items` remain exclusively for physical goods returns.
- **Eligibility:** Cancellation is allowed only before shipment. Independent refunds are allowed only for cancelled, paid orders. Physical returns are allowed only after shipment or delivery.
- **Financial ceiling:** In v1, `paid` means the full net order amount was received; partial payments are out of scope. Combined independent refunds and physical-return refunds must not exceed the net amount received.
- **Integrity:** Order financial lines become immutable after payment. Refund and return writes use tenant/order locks, idempotency, audit events and atomic transactions. Independent refunds do not change returned quantities or inventory.
- **Rationale:** Prevents synthetic returns for unshipped orders, duplicate cash refunds and divergence between money and physical-goods records.
