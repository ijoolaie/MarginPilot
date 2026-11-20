# Phase 5 — Sales & Expenses

**وضعیت:** برنامهٔ اجرایی مبتنی بر قراردادهای موجود؛ بخشی از نقشهٔ راه مصوب `docs/mvp-roadmap.md`.  
**هدف تحویل:** ثبت قابل اتکای فروش، مرجوعی و هزینه‌ها برای فراهم‌کردن ورودی واقعی موتور سود در Phase 6.  
**مراجع الزام‌آور:** `docs/data-model.md`، `docs/api-contract.md`، `docs/calculation-principles.md`، `docs/security.md` و `docs/testing-strategy.md`.

## ۱. وضعیت و مبنای شروع

جداول و endpointهای فروش/هزینه در مدل داده و قرارداد API طراحی شده‌اند؛ اما در revision فعلی migration اجرایی برای آن‌ها وجود ندارد. بنابراین این فاز پیاده‌سازی دامنه است، نه بازطراحی معماری.

دامنهٔ مدل موجود:
- `sales_orders` و `sale_items`
- `sales_returns` و `sales_return_items` به‌عنوان منبع حقیقت تغییرناپذیر مرجوعی‌ها
- `expenses` با استخر تخصیص صریح `order|product|period`

قرارداد API فعلی مسیرهای سفارش، اقلام، transition وضعیت، مرجوعی و هزینه‌ها را مشخص کرده است. هر اختلاف واقعی بین مدل/قرارداد و کد باید قبل از گسترش scope اصلاح و مستند شود.

## ۲. محدودهٔ اجرایی

### ۲.۱ فروش و اقلام
- ایجاد، فهرست، جزئیات و ویرایش سفارش طبق مسیرهای `/sales/orders`.
- افزودن/ویرایش/حذف قلم فقط در وضعیت‌های مجاز قرارداد.
- پیاده‌سازی state transitionها دقیقاً مطابق جدول وضعیت در `api-contract.md`.
- snapshot کردن نام/SKU، قیمت و بهای تمام‌شدهٔ قلم هنگام ثبت؛ `unit_cost` و `cost_source` نباید با تغییرات بعدی محصول یا تأمین‌کننده بازنویسی شوند.
- سفارش فروش soft-delete نمی‌شود؛ شمارهٔ سفارش در tenant یکتا می‌ماند و ابطال فقط با transition به `cancelled` و Audit انجام می‌شود (ADR-026). قلم فروش نیز حذف نمی‌شود؛ فقط پیش از completed طبق قرارداد قابل اصلاح/حذف است.
- تخصیص سهم تخفیف سفارش به اقلام باید با قرارداد و قواعد rounding مصوب سازگار باشد؛ محاسبهٔ سود نهایی همچنان متعلق به Phase 6 است.

### ۲.۲ مرجوعی
- ثبت مرجوعی کامل/جزئی با مسیر `POST /sales/orders/{id}/returns`.
- هر مرجوعی یک سند مستقل و immutable در `sales_returns` و `sales_return_items` است.
- جلوگیری از مرجوعی بیش از مقدار باقی‌مانده؛ قفل قلم و اعتبارسنجی/ثبت/به‌روزرسانی cache تجمعی در یک تراکنش.
- الزام `Idempotency-Key` و Audit برای ثبت مرجوعی.
- تاریخچهٔ مرجوعی سفارش از اسناد مستقل خوانده شود؛ فیلدهای تجمعی `sale_items` فقط cache مشتق‌شده‌اند.

### ۲.۳ هزینه‌ها
- CRUD کنترل‌شدهٔ هزینه با مسیرهای قرارداد `/expenses`.
- انواع مجاز: `shipping`, `packaging`, `advertising`, `payment_fee`, `operational`, `other`.
- scope باید دقیقاً یکی از `order`, `product`, `period` باشد و CHECKهای درون‌جدولی مدل را enforce کنند.
- ویرایش و soft-delete همراه Audit و جزئیات قبل/بعد.
- گزارش تفکیک هزینه‌ها بر اساس نوع مطابق endpoint موجود.
- تخصیص واقعی هزینه و اثر آن بر سود در این فاز انجام نمی‌شود؛ Phase 6 مسئول مصرف استخرها و قواعد allocation است.

### ۲.۴ Sales import
- فعال‌سازی `kind=sales` فقط پس از تکمیل و تست persistence و سرویس‌های فروش.
- حفظ الگوی validate → preview → confirm، ثبت خطا/duplicate، commit اتمیک، idempotency و tenant isolation.
- پیش از پیاده‌سازی، mapping دقیق ستون‌های سفارش/اقلام و قواعد گروه‌بندی ردیف‌ها در `api-contract.md` ثبت شود؛ از حدس دربارهٔ ساختار فایل ورودی خودداری شود.
- import باید از همان domain services عملیات دستی استفاده کند؛ منطق نوشتن مستقل و موازی ایجاد نشود.
- import ناقص/نامعتبر نباید سفارش نیمه‌کاره باقی بگذارد؛ سیاست commit ردیف‌های معتبر باید با ساختار سفارش/اقلام سازگار و صریح باشد.

## ۳. الزامات داده و امنیت

- تمام روابط tenant-owned با FKهای مرکب مطابق `data-model.md` پیاده شوند؛ فیلتر کد به‌تنهایی کافی نیست.
- ارز سفارش و هزینه در زمان نوشتن با ارز tenant تطبیق داده شود.
- تمام مقادیر پولی با Decimal و NUMERIC؛ float ممنوع.
- قیود مقدار مثبت، تخفیف/بازپرداخت غیرمنفی، یکتایی شماره سفارش/مرجوعی و سازگاری scope در DB enforce شوند.
- سوابق فروش/مرجوعی hard-delete نشوند؛ مرجوعی immutable باشد.
- RBAC، Audit، rate limits و idempotency مطابق قرارداد موجود.
- migration افزایشی باشد؛ migrationهای منتشرشدهٔ قبلی بازنویسی نشوند.

## ۴. ترتیب تحویل درون فاز

این موارد workstreamهای یک فاز هستند، نه فازهای مجزا:
1. تطبیق نهایی مدل/قرارداد با کد موجود و ثبت mapping فروش؛ رفع فقط تناقض‌های واقعی.
2. migration و مدل‌های SQLAlchemy برای پنج جدول دامنه؛ upgrade/check/downgrade/upgrade روی PostgreSQL واقعی.
3. سرویس‌های تراکنشی فروش، transitionها، مرجوعی و هزینه.
4. API، RBAC و Audit و تست‌های integration.
5. Sales import با استفاده از domain services.
6. بازبینی مستقل، اصلاح مستندات و اجرای کامل CI.

## ۵. معیارهای پذیرش

### Database
- migration upgrade، downgrade به revision قبلی و upgrade مجدد موفق.
- `alembic check` بدون drift.
- FKهای tenant-aware و FK سه‌ستونهٔ variant↔product در DB enforce شوند.
- CHECKها، unique indexes و indexهای FK لازم بررسی شوند.

### Domain & API
- تست گذارهای مجاز/غیرمجاز سفارش.
- snapshot بهای تمام‌شده و منبع آن در قلم فروش.
- تست مرجوعی جزئی، کامل، چندسندی و رقابت هم‌زمان دو مرجوعی روی یک قلم.
- تست Idempotency replay و conflict.
- تست scopeهای سه‌گانهٔ هزینه و حذف نرم/Audit.
- تست ارز tenant، RBAC و عدم دسترسی cross-tenant.
- پاسخ API با قرارداد و schema مستند منطبق باشد.

### Import
- تست فایل معتبر/نامعتبر، mapping، duplicate، preview، commit و rollback.
- retry یکسان idempotent و کلید با payload متفاوت conflict بدهد.
- هیچ سفارش/قلم ناقص یا دادهٔ بین tenantها ایجاد نشود.

### Quality gates
- unit و PostgreSQL integration tests سبز.
- Ruff، mypy، pip check و pip-audit سبز.
- frontend regressions در CI سبز.
- مستندات `data-model.md`، `api-contract.md`، `phase5-plan.md` و `CHANGELOG.md` هم‌راستا.
- CI GitHub برای commit نهایی موفق؛ تست محلی جایگزین CI نیست.

## ۶. خارج از محدوده

- موتور محاسبهٔ سود، تحلیل دوره و قیمت پیشنهادی (Phase 6).
- داشبورد، رابط کاربری کامل فروش/هزینه و گزارش‌های نهایی (Phase 7).
- حسابداری دوبل، دفترکل، انبارداری جامع، سفارش خرید و پرداخت تأمین‌کننده.
- پردازش async/صف؛ مگر تست واقعی نشان دهد پردازش synchronous از بودجهٔ زمانی/حافظه خارج است.

## ۷. نکتهٔ باز برای شروع کدنویسی

قرارداد Sales import در سند API فعلی `sales` را رزرو کرده و صریحاً `422 IMPORT_KIND_NOT_READY` می‌دهد؛ mapping دقیق ورودی فروش هنوز در بخش mapping فعلی تعریف نشده است. این قرارداد باید قبل از فعال‌سازی import تکمیل شود. سایر ساختارهای فروش/مرجوعی/هزینه در مدل داده و API موجودند و مبنای پیاده‌سازی‌اند.
