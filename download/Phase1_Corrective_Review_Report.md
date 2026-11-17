# گزارش بازبینی اصلاحی Phase 1 — MarginPilot

**تاریخ:** ۲۰۲۶-۱۱-۱۶ · **محدوده:** فقط اصلاح سندهای Phase 1 طبق بازبینی فنی — بدون Phase 2، بدون پیاده‌سازی، بدون commit/push/merge.

## ۱) فایل‌های اصلاح‌شده

| فایل | نوع تغییر |
|---|---|
| docs/calculation-principles.md | بازنویسی کامل — مدل یکپارچهٔ تخفیف، RETURN_LOSS علامت‌دار، قواعد کامل تخصیص/مرجوعی، ۲۰ بردار + V8b، فرمول FV-2 |
| docs/data-model.md | بازنویسی کامل — ۲۱ FK مرکب tenant-aware، جداول جدید product_price_history و idempotency_keys، قواعد یکتایی اجراپذیر، سازگاری ارز، «هدف» هر ۲۷ جدول |
| docs/api-contract.md | بازنویسی کامل — مجوز صریح هر endpoint، طراحی کامل Idempotency، گذارهای وضعیت، سیاست ثبت‌نام، سازگاری API↔RBAC |
| docs/security.md | بازنویسی کامل — CSRF متصل به نشست، حذف JWT از reset، حاکمیت ثبت‌نام/Owner/عضویت، مجوز دانلودها |
| docs/architecture.md | ۷ ویرایش هدف‌مند — حذف billing از ماژول‌ها/قراردادها/ساختار، قانون ۷ (یکپارچگی DB)، FV-2 |
| docs/decisions.md | ADR-003 به‌روزرسانی (بدون JWT)، ADR-013 بازنویسی (حذف billing)، افزودن ADR-018..021 |
| docs/testing-strategy.md | قاعدهٔ ۸ (Coverage≠صحت مالی)، سوییت‌های الزامی بازبینی (۸ سوییت) |
| docs/dependencies.md | حذف PyJWT از وابستگی‌ها |
| .env.example | حذف CSRF_COOKIE_NAME، APP_SECRET=reserved، متغیرهای ثبت‌نام/Idempotency/Audit |
| README.md | شمارش ADR (۲۱)، وضعیت Phase 1 |
| backend/app/modules/billing/ | **حذف کامل پوشه** (طبق P2 بازبینی) |
| download/marginpilot-phase1-20261116.zip | بازتولید با محتوای اصلاح‌شده (تست یکپارچگی: OK) |

## ۲) خلاصهٔ هر اصلاح

**P0-محاسبات (A):** (۱) مدل یکپارچه: تخفیف فقط یک‌بار داخل NLR؛ فرمول Net Operating Profit هیچ جملهٔ تخفیفی ندارد (FV-2). (۲) return_variance علامت‌دار + RETURN_LOSS=max(v,0) همیشه مثبت؛ بردار V8 اصلاح شد (قبلاً به‌اشتباه «زیان ۱۰٬۰۰۰» بود، در واقع variance=−10,000 → GAIN 10,000) + V8b برای refund بالاتر از ارزش. (۳) قواعد دقیق: مرجوعی کامل/جزئی، سفارش لغوشده، هزینهٔ دوره، هزینهٔ order-scoped، دورهٔ بدون فروش، cost نامشخص، مرجوعی پس از دوره (بدون قفل دوره در v1). (۴) منع تخصیص دوگانه: استخرهای مجزا بر اساس allocation_scope. (۵) تخصیص پس از مرجوعی با دلیل مستند. (۶/۷) بردارهای V1–V20 همه با محاسبهٔ دستی قابل راستی‌آزمایی و زنجیرهٔ عددی سازگار.

**P0-Tenant DB (B):** ۲۱ FK مرکب `(tenant_id, parent_id)` به `UNIQUE(tenant_id, id)` والد — PostgreSQL خودش ارجاع متقاطع را رد می‌کند؛ رفتار FK با ستون اختیاری (MATCH SIMPLE) مستند؛ قواعد سه‌گانهٔ تکمیلی سرویس (variant↔product، session membership، ارز) با تست integration.

**P0-مدل داده (C):** (۱) جدول product_price_history + ستون‌های sale_price/purchase_cost روی products. (۲) روابط variant با sale_items با FK مرکب + قاعدهٔ والد. (۳) دو partial unique index صریح برای supplier_prices جایگزین نماد مبهم. (۴) قواعد ارز (§۷). (۵) نقش‌ها سراسری سیستمی؛ مسیر نقش tenant-specific مستند برای آینده. (۶) روابط audit + نگهداری ≥۴۰۰ روز؛ entity_id عمداً بدون FK. (۷) provenance: snapshotها + calculations.input + formula_version. (۸) «هدف» صریح هر ۲۷ جدول. (۹) حذف billing از ساختار.

**P1-Idempotency (G):** جدول idempotency_keys با scope (tenant,user,key)، هش payload کانونی، snapshot پاسخ، TTL ۲۴h، رفتار هم‌زمانی (unique constraint → در جریان: `IDEMPOTENCY_IN_PROGRESS`)، شکست → آزادسازی کلید، payload متفاوت → `IDEMPOTENCY_CONFLICT`؛ عملیات الزامی: import confirm، report، comparison run، return.

**P1-امنیت (D,F,H):** CSRF متصل به نشست (توکن per-session، هش در DB، تحویل با هدر — مقاوم به Cookie Injection) + جدول رفتار CSRF برای login/register/logout/switch/password/report؛ reset = توکن تصادفی یک‌بارمصرف بدون JWT (PyJWT حذف شد)؛ سیاست ثبت‌نام (rate limit ۳/h، ALLOW_REGISTRATION، سقف tenant، blacklist slug، عدم تأیید ایمیل مستند‌شده)؛ قاعدهٔ تنها Owner (`SOLE_OWNER_PROTECTED`)؛ لغو عضویت → به‌روزرسانی فوری نشست‌ها؛ مجوز دانلود گزارش/خطای import با scope tenant.

**P1-API/RBAC (E):** تأیید تطبیق‌های comparison → `comparison:write`؛ افزودن `member:read` و `comparison:read`؛ فهرست ۲۰ کد مجوز = دقیقاً ماتریس RBAC؛ هر endpoint مجوز صریح دارد؛ گذارهای وضعیت orders/payment/shipping/imports جدول‌بندی شد؛ lowest-price فقط هم‌ارز tenant و هم‌unit (excluded_units)؛ profit = on-demand + ژورنال با formula_version و calculation_id؛ تاریخچهٔ قیمت از product_price_history.

**P2:** billing حذف از اسکلت (مصرف‌کننده ندارد)؛ analytics همچنان فقط از موتور pricing؛ ۸ سوییت تست جدید + قاعدهٔ «Coverage≠صحت مالی» + گیت پروتوتایپ PDF فارسی در ابتدای مسیر گزارش‌گیری.

## ۳) شمارش‌های به‌روز ERD

**۲۷ جدول** (۱۱ سراسری + ۱۶ tenant-owned) · **۴۳ رابطه** در ERD · **۲۱ FK مرکب tenant-aware** · ۲ جدول جدید (product_price_history، idempotency_keys) · +۱ ستون (sessions.csrf_token_hash، sales_orders.order_discount، products.sale_price/purchase_cost).
> تصحیح صادقانه: گزارش قبلی «۲۳ جدول» گفته بود که نادرست بود (واقعی: ۲۵)؛ اکنون ۲۷.

## ۴) بردارهای مالی به‌روز (FV-2 — جزئیات کامل: calculation-principles §۸)

۲۰ بردار شماره‌دار + V8b؛ تغییرات کلیدی: **V6** گارد شمارش دوگانه (NLR=940,000 → Net=340,000؛ دوباره‌شماری می‌شد 330,000) · **V8** تصحیح علامت (variance=−10,000 → RETURN_GAIN=10,000، RETURN_LOSS=0، Gross_after=290,000 با هویت سازگاری) · **V8b** refund بالاتر از ارزش (variance=+10,000 → LOSS 10,000) · **V15** دورهٔ بدون فروش · **V16** مرجوعی کامل · **V17** هزینهٔ سفارش لغوشده · **V18** cost نامشخص · **V19** تفکیک استخرها · **V20** تخصیص پس از مرجوعی. FV-1 باطل شد.

## ۵) فهرست کامل FKهای مرکب tenant-aware (۲۱)

sale_items→sales_orders · sale_items→products · sale_items→product_variants · products→categories · product_variants→products · categories→categories(parent) · supplier_price_lists→suppliers · supplier_prices→supplier_price_lists · supplier_prices→suppliers · supplier_prices→products · expenses→sales_orders · expenses→products · comparison_runs→supplier_price_lists (×2) · comparison_matches→comparison_runs · comparison_matches→supplier_prices (×2) · comparison_matches→products (×2) · import_rows→imports · product_price_history→products — همه به شکل `(tenant_id, parent_id)` با پیش‌نیاز `UNIQUE (tenant_id, id)` روی والدین.

## ۶) نتیجهٔ سازگاری API ↔ RBAC

۲۰ کد مجوز در فهرست = دقیقاً همان ماتریس RBAC در security §۴؛ همهٔ endpointهای api-contract §۳ مجوز صریح دارند؛ هیچ endpoint بدون مجوز و هیچ مجوز بدون endpoint نیست؛ کنترل خودکار این سازگاری در CI از Phase 3 برنامه‌ریزی شد. اصلاحات: comparison:write (تأیید تطبیق)، member:read و comparison:read (مطالعه).

## ۷) خلاصهٔ طراحی Idempotency

ذخیره در `idempotency_keys` · scope `(tenant_id, user_id, key)` unique · request_hash = SHA-256 از JSON کانونی · snapshot پاسخ (status+body) با هدر `Idempotent-Replayed: true` · TTL ۲۴ ساعت + پاک‌سازی · هم‌زمانی: درج با unique constraint → دوم یا replay یا `409 IDEMPOTENCY_IN_PROGRESS` · شکست تراکنش → حذف ردیف کلید (retry ممکن) · payload متفاوت → `409 IDEMPOTENCY_CONFLICT` · عملیات الزامی v1: import confirm، report، comparison run، return.

## ۸) ریسک‌ها و تصمیم‌های باز

R1 ارزهای خارجی (USD و…) خارج از v1 — مدل آینده ستون original_currency دارد · R2 عدم تأیید ایمیل در v1 (سرویس ایمیل نیست) — جبران با rate limit + کنترل ادمین؛ در فاز بعدی سرویس ایمیل کامل می‌شود · R3 عدم قفل دوره: مرجوعی دیرهنگام محاسبات بعدی را اصلاح می‌کند؛ گزارش‌ها مهر «داده تا تاریخ X» دارند — قفل دوره در آینده قابل افزودن است · R4 یکتایی SKU بین products/variants در سرویس (محدودیت DB) — تست الزامی · R5 اعتبار session.tenant_id و زوج variant↔product در سرویس (FK cross-table ندارد) — تست الزامی · R6 RLS PostgreSQL به‌عنوان سخت‌سازی آینده (ADR-018) · R7 ماتریس سازگاری TS7/Vite8/Zod4 در Phase 2 با نصب و build واقعی اجرا می‌شود (تصمیم بازبینی — قابل انتقال به Phase 2) · R8 پروتوتایپ PDF فارسی/RTL باید در ابتدای مسیر گزارش‌گیری اجرا شود (گیت تست).

## ۹) شواهد راستی‌آزمایی (اجرای واقعی)

1. `Discounts_not_in_Revenue` → GONE · `CSRF_COOKIE_NAME` → GONE · علامت اشتباه قبلی V8 → GONE
2. اسکن JWT: فقط در بافت رد/رزرو؛ `PyJWT` از dependencies.md حذف (اسکن CLEAN)
3. billing: فقط ۴ اشارهٔ future-scope مستند؛ پوشه از backend حذف (۱۱ ماژول)
4. `confirm-matches` → comparison:write ✓
5. شمارش: ۲۷ جدول (grep pattern «هدف») · ۴۳ رابطه ERD · ۲۱ FK مرکب · ۲۱ ردیف بردار · ۲۰ کد مجوز
6. توازن fenceها EVEN · اسکن placeholder (【/TODO/XXX) CLEAN
7. zip بازتولید و `unzip -t` → «No errors detected» (۴۹ فایل، ۶۸KB)

## ۱۰) تأیید مرزها

✅ هیچ قابلیت محصولی، endpoint، migration، Docker یا کار Phase 2 انجام نشد — فقط سندهای طراحی و اسکلت (حذف پوشهٔ خالی billing). ✅ هیچ commit، push یا merge انجام نشد — آخرین commit همچنان `48a3f55` است و همهٔ تغییرات فقط در working tree است.

**وضعیت:** بازبینی اصلاحی COMPLETED — **توقف برای بازبینی مستقل شما**. شروع Phase 2 فقط پس از تأیید صریح.
