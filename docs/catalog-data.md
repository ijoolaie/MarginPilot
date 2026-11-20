# Catalog & Supplier Persistence — Phase 4 Step 1

این سند جزئیات اجرایی schema را در کنار قرارداد اصلی `data-model.md` ثبت می‌کند. مدل‌ها هنوز API یا منطق CRUD ندارند.

## جداول و قیود

| جدول | قیود و رفتارهای مهم |
|---|---|
| `categories` | self-reference مرکب `(tenant_id, parent_id)`؛ دو partial unique index جدا برای دسته ریشه و فرزند زنده؛ دسته حذف‌شده نام را رزرو نمی‌کند. |
| `products` | FK مرکب به category؛ SKU درون جدول برای ردیف‌های زنده یکتا؛ واحد محدود به `piece`, `kg`, `liter`, `meter`, `box`؛ قیمت‌های مرجع nullable و غیرمنفی. |
| `product_variants` | FK مرکب به محصول؛ یکتایی SKU زنده در جدول؛ کلید یکتای سه‌ستونه `(tenant_id, product_id, id)` برای ارجاع آتی اقلام فروش. |
| `product_price_history` | FK مرکب به محصول و قیمت تأمین‌کننده؛ منبع `supplier_price` دقیقاً با وجود `supplier_price_id` جفت است؛ تغییر نوع فقط `purchase`/`sale`. |
| `suppliers` | tenant-owned؛ اطلاعات تماس اختیاری؛ soft delete و وضعیت فعال. |
| `supplier_price_lists` | FK مرکب به تأمین‌کننده؛ creator به users؛ source=`manual/import` و status=`draft/final`. |
| `supplier_prices` | FK مرکب به لیست و محصول اختیاری؛ `supplier_id` ذخیره نمی‌شود؛ قیمت غیرمنفی و ارز محدود به IRT/IRR؛ دو partial unique index مطابق وجود/عدم وجود SKU. |

تمام هفت جدول دارای `tenant_id` و FK به tenants هستند. روابط tenant-owned با FK مرکب پیاده شده‌اند تا PostgreSQL به‌صورت مستقل از فیلترهای برنامه، اتصال رکوردهای دو tenant را رد کند.

## تصمیم‌های مهم و مرزها

1. قیمت‌های پولی `NUMERIC(20,2)` هستند و در Python به `Decimal` نگاشت می‌شوند.
2. ارز در لحظه نوشتن باید با ارز tenant برابر باشد؛ تطبیق بین دو جدول در سرویس انجام می‌شود، چون cross-table CHECK در PostgreSQL مناسب نیست و trigger در v1 انتخاب نشده است.
3. SKU بین products و product_variants قاعدهٔ cross-table است. DB با partial indexهای هر جدول، یکتایی درون هر جدول را تضمین می‌کند؛ سرویس Catalog باید یکتایی مشترک را با تراکنش/قفل مناسب enforce کند.
4. تأیید price list نباید `products.purchase_cost` را خودکار تغییر دهد. اقدام صریح کاربر برای تنظیم بهای مرجع باید در گام سرویس، هم محصول و هم provenance در `product_price_history` را در یک تراکنش ثبت کند.
5. FKهای تاریخی با `RESTRICT` مانع حذف سخت موجودیت‌هایی می‌شوند که سابقه قیمت یا ارجاع فعال دارند؛ مسیر معمول حذف، soft delete است.

## اعتبارسنجی

تست‌های PostgreSQL واقعی در `backend/tests/integration/test_catalog_schema.py` موارد زیر را پوشش می‌دهند: حضور جداول، cross-tenant FKها، دسته‌های درختی و partial uniqueness، soft-delete reuse، SKU محصول/واریانت، یکتایی اقلام لیست قیمت، provenance و Decimal، و CHECKهای واحد/قیمت/ارز.

## Phase 4 Step 2 — Service and API behavior

- Catalog and Supplier endpoints are registered under `/api/v1` and require the active tenant context plus `product:read/write` or `supplier:read/write`.
- Product and supplier list endpoints use bounded pagination (`page_size` 1–100); product filters include name/SKU, category, active status and supplier.
- Product price changes are recorded only for explicit price changes. Initial non-null prices create a history row with `old_price=null`.
- Cross-table SKU uniqueness is serialized by locking the tenant row before product/variant writes; this closes the race that independent partial unique indexes cannot close.
- Supplier price lists are created as `draft`; finalization requires at least one item. A final list cannot be changed or deleted; a draft can be deleted.
- Every new supplier price item carries `unit`. The additive migration `a7c19d4e6f20` leaves the column nullable only for legacy rows; new API requests require one of `piece`, `kg`, `liter`, `meter`, `box`.
- A price row may be linked to a product while retaining a different supplier unit; lowest-price excludes that unit and reports it. Applying a supplier price to `products.purchase_cost` requires a final, tenant-currency, same-unit price and writes `product_price_history.supplier_price_id` atomically.
- Supplier list finalization does not update product purchase cost automatically.

### Additional endpoints

- `POST /products/{id}/purchase-cost-from-supplier-price`
- `POST /price-lists/{id}/finalize`
- `DELETE /price-lists/{id}` (draft only)

### Known limits

- Unit conversion and foreign-currency conversion are not implemented.
- Unmatched supplier rows (`product_id=null`) are not included in a product's lowest-price result.
- Final price lists are immutable; corrections require a replacement list.
