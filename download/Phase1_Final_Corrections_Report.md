# گزارش اصلاحات نهایی Phase 1 — MarginPilot (دور دوم بازبینی)

**تاریخ:** ۲۰۲۶-۱۱-۱۶ · **دامنه:** فقط موارد باقی‌ماندهٔ بازبینی مستقل دوم — معماری از نو نوشته نشد و تصمیم‌های تأییدشدهٔ قبلی حفظ شدند.

## ۱) فهرست دقیق فایل‌های اصلاح‌شده

| فایل | تغییر |
|---|---|
| docs/data-model.md | جداول جدید sales_returns و sales_return_items؛ FK سه‌ستونهٔ variant؛ حذف supplier_id از supplier_prices؛ تفکیک سه مفهوم بهای خرید؛ سیاست product_price_history؛ یکتایی دستهٔ حذف‌شده؛ idempotency تراکنش واحد؛ indexها؛ شمارش‌ها؛ provenance هزینه‌ها |
| docs/api-contract.md | §۱.۵ بازنویسی (مدل تراکنش واحد + هش کامل)؛ حذف IDEMPOTENCY_IN_PROGRESS از جدول خطاها؛ شمارش ۲۰؛ endpoint مرجوعی + GET returns؛ POST /comparison/runs → comparison:write؛ یادداشت نقش‌ها |
| docs/security.md | قواعد Origin/Referer غایب؛ دامنهٔ comparison:write و تصمیم Analyst؛ قفل تراکنشی تنها Owner |
| docs/calculation-principles.md | منبع حقیقت مرجوعی؛ منابع provenance (sales_return_items، supplier_prices) |
| docs/testing-strategy.md | تست هم‌زمانی Idempotency مطابق مدل جدید؛ سوییت مرجوعی چندگانه با lock |
| docs/decisions.md | ADR-022 (مرجوعی درجه‌یک)، ADR-023 (Idempotency تراکنش واحد)، ADR-024 (FK سه‌ستونه + حذف supplier_id) |
| .env.example | APP_SECRET حذف شد (بدون مصرف‌کننده در v1) |
| README.md | شمارش ADR: ۲۴ |
| scripts/make_phase1_zip.sh | جدید — ساخت آرشیو با manifest راستی‌آزمایی |
| download/PHASE1_MANIFEST.txt | جدید — وضعیت git، اثبات ignore شدن .env، SHA-256 سندها |
| download/marginpilot-phase1-20261116.zip | بازتولید — **گزارش‌های بازبینی داخل آرشیو هستند** (رفع ایراد گزارش‌شده) |

## ۲) شمارش‌های به‌روز

**۲۹ جدول** (۱۱ سراسری + ۱۸ متعلق به tenant — +۲ جدول مرجوعی) · **۴۸ رابطه** ERD (+۵: sales_returns×۲، sales_return_items×۲، product_price_history←supplier_prices) · **۲۴ FK مرکب tenant-aware** · ۲۱ ردیف بردار مالی (V1–V20 + V8b) · **۲۰ کد مجوز**.

## ۳) فهرست کامل ۲۴ FK مرکب tenant-aware

1. sale_items (tenant_id, order_id) → sales_orders
2. sale_items (tenant_id, product_id) nullable → products
3. **sale_items (tenant_id, product_id, variant_id) nullable → product_variants (tenant_id, product_id, id)** — سه‌ستونه
4. products (tenant_id, category_id) nullable → categories
5. product_variants (tenant_id, product_id) → products
6. categories (tenant_id, parent_id) nullable → categories
7. supplier_price_lists (tenant_id, supplier_id) → suppliers
8. supplier_prices (tenant_id, price_list_id) → supplier_price_lists
9. supplier_prices (tenant_id, product_id) nullable → products
10. expenses (tenant_id, order_id) nullable → sales_orders
11. expenses (tenant_id, product_id) nullable → products
12–13. comparison_runs (tenant_id, base_list_id / target_list_id) → supplier_price_lists
14. comparison_matches (tenant_id, run_id) → comparison_runs
15–16. comparison_matches (tenant_id, base_price_id / target_price_id) → supplier_prices
17–18. comparison_matches (tenant_id, suggested_product_id / confirmed_product_id) → products
19. import_rows (tenant_id, import_id) → imports
20. product_price_history (tenant_id, product_id) → products
21. **product_price_history (tenant_id, supplier_price_id) nullable → supplier_prices** — provenance
22. **sales_returns (tenant_id, order_id) → sales_orders**
23. **sales_return_items (tenant_id, return_id) → sales_returns**
24. **sales_return_items (tenant_id, sale_item_id) → sale_items**

## ۴) جریان به‌روز Idempotency (مدل تراکنش واحد — MVP)

رزرو کلید + اجرای عملیات + ذخیرهٔ پاسخ **در یک تراکنش**؛ درخواست هم‌زمان تا پایان تراکنش اول روی قید یکتایی `(tenant_id, user_id, key)` قفل می‌شود → commit اول ⇒ replay پاسخ با `Idempotent-Replayed: true`؛ rollback اول ⇒ کلید آزاد و retry ممکن. `IDEMPOTENCY_IN_PROGRESS` **حذف شد** (مدل رزرو مستقل در v1 نیست — مستند در §۱.۵ و ADR-023). هش درخواست = SHA-256 از **method + path نرمال‌شده + operation + body کانونی‌شده**. TTL ۲۴h. همان key با درخواست متفاوت → `IDEMPOTENCY_CONFLICT`.

## ۵) نتیجهٔ سازگاری API ↔ RBAC

۲۰ کد مجوز (شمارش در هر دو سند یکسان شد؛ «۲۱» باقی‌مانده حذف شد) — `platform_admin` صریحاً «نقش، نه کد مجوز» ثبت شد. `POST /comparison/runs` → `comparison:write` (ایجاد)، GETها → `comparison:read`، تأیید تطبیق‌ها → `comparison:write`؛ تصمیم صریح: **Analyst در v1 نمی‌تواند مقایسه بسازد/تأیید کند** (فقط owner/admin) — در ماتریس RBAC و api-contract §۶ هر دو ثبت شد. کنترل خودکار سازگاری در CI از Phase 3.

## ۶) مدل مرجوعی و یکپارچگی Variant/Product

**مرجوعی:** `sales_returns` (سربرگ: سفارش، تاریخ، کاربر، status=committed، متادیتای بازپرداخت، return_number یکتا) و `sales_return_items` (قلم، مقدار، مبلغ، snapshot) — منبع حقیقت؛ فیلدهای تجمعی sale_items فقط **کش مشتق‌شده** است که در همان تراکنش commit به‌روزرسانی می‌شود. قواعد: جمع مرجوعی هر قلم ≤ مقدار فروخته‌شده؛ اعتبارسنجی با lock روی sale_item در یک تراکنش (دو مرجوعی هم‌زمان: یکی commit، دیگری خطا با مقدار به‌روز)؛ Idempotency-Key اجباری؛ رکوردها تغییرناپذیر (اصلاح = سند جبرانی آینده)؛ هر ثبت → Audit. بازتولید تاریخی از رکوردهای مرجوعی انجام می‌شود نه از مقادیر تجمعی. ERD/API/محاسبات/تست‌ها هم‌زمان به‌روز شدند.

**Variant/Product:** با FK سه‌ستونه به کلید مرجع `UNIQUE (tenant_id, product_id, id)` روی product_variants، تعلق variant به همان product **در DB** تضمین می‌شود (سناریوی «محصول ۱۰ + variant محصول ۲۰» ناممکن شد)؛ CHECK مکمل `variant_id IS NOT NULL ⇒ product_id IS NOT NULL` جلوی ترکیب ناقص را می‌گیرد. کنترل صرفاً سرویس‌محور حذف شد.

**Baha-ye kharid (سه مفهوم):** بهای مرجع محصول (`products.purchase_cost` + تاریخچه) فقط با اقدام صریح تغییر می‌کند؛ تاریخچهٔ هر تأمین‌کننده در `supplier_prices` لیست‌های final؛ بهای واقعی هر فروش در `sale_items.unit_cost` تغییرناپذیر. تأیید لیست قیمت فقط status لیست را به final می‌برد و **هرگز** بهای مرجع را تغییر نمی‌دهد؛ منبع هر تغییر بهای مرجع در `product_price_history.supplier_price_id` ثبت می‌شود. `supplier_prices.supplier_id` حذف شد (تأمین‌کننده از لیست استخراج می‌شود).

## ۷) ریسک‌ها و تصمیم‌های باز

R1 عدم تأیید ایمیل در v1 (سرویس ایمیل نیست) — با rate limit و کنترل ادمین مهار می‌شود · R2 عدم قفل دوره: مرجوعی/اصلاح هزینه دیرهنگام فقط محاسبات بعدی را عوض می‌کند؛ گزارش‌ها مهر «داده تا تاریخ X» — قفل دوره در آینده · R3 مرجوعی تغییرناپذیر در v1 (سند جبرانی آینده) — محدودیت مستند · R4 یکتایی SKU بین products/variants و اعتبار session.tenant_id در سرویس (محدودیت FK) — تست الزامی · R5 سقف تجمعی مرجوعی قید سرویس است (با lock تراکنشی)؛ قید DB مستقیم ممکن نیست — تست هم‌زمانی الزامی · R6 رد درخواست‌های فاقد Origin/Referer ممکن است کلاینت‌های غیرمرورگری را بلاک کند — تصمیم مستند v1 · R7 RLS به‌عنوان سخت‌سازی آینده (ADR-018) · R8 ماتریس سازگاری نسخه‌ها → Phase 2 با نصب/build واقعی · R9 گیت پروتوتایپ PDF فارسی/RTL در ابتدای مسیر گزارش‌گیری.

## ۸) شواهد راستی‌آزمایی (اجرای واقعی)

1. شمارش با grep: **۲۹** جدول (الگوی «هدف») · **۴۸** رابطه ERD (`||--`) · **۲۴** ردیف FK مرکب · **۲۱** ردیف بردار
2. `IDEMPOTENCY_IN_PROGRESS` فقط در دو بافت «حذف شد/انتخاب نشد» (ADR-023، api §۱.۵) — متن تست قدیمی در testing-strategy اصلاح شد
3. شمارش مجوز «۲۱» GONE؛ `APP_SECRET` از .env.example GONE؛ `supplier_id` در مشخصات supplier_prices فقط به‌صورت «حذف شد»
4. `POST /comparison/runs` → `comparison:write` ✓ · جدول‌های sales_returns/sales_return_items با FKهای مرکب ✓ · FK سه‌ستونه + کلید مرجع ✓
5. توازن fenceها EVEN · placeholder scan CLEAN
6. git: HEAD=`096d4d9` (checkpoint خودکار session بین دو دور اصلاح — خارج از اقدامات من)؛ **۸ فایل این دور بدون commit در working tree**؛ `.env` git-ignored ✓ (اثبات در PHASE1_MANIFEST.txt)
7. آرشیو: ۵۲ فایل، `unzip -t` → «No errors detected» — **هر چهار گزارش بازبینی + manifest داخل آرشیو**

## ۹) تأیید مرزها

✅ هیچ پیاده‌سازی محصولی، migration، Docker یا نصب وابستگی انجام نشد — فقط اسناد طراحی، حذف قبلی پوشهٔ billing، و آرشیو/گزارش‌ها. ✅ هیچ commit، push یا merge توسط من انجام نشد — تغییرات این دور در working tree است؛ commit میانی `096d4d9` checkpoint خودکار محیط بود (شفاف‌سازی صادقانه، خارج از کنترل من).

**وضعیت:** اصلاحات نهایی COMPLETED — **توقف برای بازبینی مستقل و تأیید صریح شما**. Phase 2 شروع نمی‌شود.
