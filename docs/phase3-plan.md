# برنامهٔ Phase 3 — هویت، چندمستاجری و پایگاه‌داده

## مبنای برنامه

این برنامه ادامهٔ مستقیم قراردادهای مصوب `architecture.md`، `data-model.md`، `api-contract.md` و `security.md` است. Phase 2 با تکمیل زیرساخت و راستی‌آزمایی Compose/CI بسته شد. Phase 3 قابلیت‌های Identity و Tenancy را روی PostgreSQL واقعی پیاده می‌کند؛ معماری همچنان Modular Monolith است.

## Step 1 — Persistence Foundation و Schema پایه

- راه‌اندازی Alembic متصل به `DATABASE_URL` معتبر برنامه؛ بدون `create_all()` و بدون اجرای خودکار Migration هنگام startup.
- تعریف SQLAlchemy Declarative Base و naming convention پایدار برای constraintها.
- ایجاد Migration اولیه برای ۱۱ جدول سراسری: کاربران، tenantها، نقش‌ها، مجوزها، عضویت‌ها، نشست‌ها، reset tokenها، تنظیمات tenant، audit و idempotency.
- اعمال `citext` برای یکتایی case-insensitive ایمیل.
- seed idempotent پنج نقش سیستمی و ۲۰ مجوز مطابق ماتریس RBAC؛ هیچ کاربر یا رمز پیش‌فرضی ساخته نمی‌شود.
- تست واقعی PostgreSQL برای upgrade، بررسی تطابق metadata با schema، downgrade/upgrade و seedها.
- قرار دادن Migrationها در Backend image و مستندسازی اجرای یک‌بارهٔ آن.

**خارج از Step 1:** routeهای Auth/Tenant، رمزنگاری رمز عبور، ساخت نشست در runtime، CRUD، جداول دامنهٔ ۱۸گانه و هرگونه دادهٔ نمونه.

## Step 2 — Identity و Session Security

- Argon2id با وابستگی دقیق pin/hash و سیاست رمز مطابق قرارداد.
- Implementation details and operational constraints: `identity-sessions.md`.
- ثبت‌نام و ورود با کنترل‌های Origin، rate limit و قفل تدریجی؛ پیام‌های ورود ناموفق بدون افشای وجود حساب.
- نشست opaque با توکن تصادفی CSPRNG؛ فقط SHA-256 token hash و CSRF hash در DB.
- کوکی `mp_session` با `HttpOnly`، `Secure` در HTTPS، `SameSite=Lax` و انقضای idle/absolute.
- logout، `/auth/me`، تغییر رمز و ابطال نشست‌ها؛ تست ابطال فوری و CSRF.
- بازیابی رمز: ذخیره و مصرف یک‌بارمصرف token قابل پیاده‌سازی است، اما ارسال امن ایمیل خارج از scope فعلی است؛ هیچ token خامی به API، log یا محیط production افشا نمی‌شود. endpoint درخواست reset تا تعیین کانال تحویل امن فعال نمی‌شود.

## Step 3 - Tenancy & RBAC

- Implemented atomic user/tenant/initial Owner registration, behind `ALLOW_REGISTRATION=false` by default, with per-IP rate limiting and per-user tenant cap.
- Implemented tenant create/list/activate/update routes and server-side `TenantContext` resolved from the opaque session and an active membership.
- Implemented backend permission dependencies from the seeded role/permission matrix. `platform_admin` has no tenant-level access.
- Implemented tenant-scoped member list/add/update/revoke; invitations and Owner transfer remain out of scope.
- Last active Owner protection uses tenant-row locking, returns `409 SOLE_OWNER_PROTECTED`, and writes an audit event. Cross-tenant path IDs return 404.
- Details, limitations, and API behavior: `tenancy-rbac.md`.


## معیارهای پذیرش Phase 3

- Migrationها فقط از Alembic و قابل بازتولید باشند؛ هیچ `create_all()` در runtime یا تست integration وجود نداشته باشد.
- همهٔ تست‌ها روی PostgreSQL واقعی اجرا شوند؛ SQLite و mock جایگزین integration نیستند.
- CI شامل lint، typing، unit، migration round-trip و integration باشد.
- هیچ secret، password خام، session token یا CSRF token در DB/log/repository ذخیره نشود.
- قراردادهای API و امنیتی مرجع باقی بمانند؛ هر تناقض قبل از پیاده‌سازی با سند تصمیم ثبت شود.
- هر Step جداگانه تحویل و بررسی شود؛ Step بعدی تا تأیید مستقل Step جاری آغاز نمی‌شود.

## ترتیب استقرار Migration

Migration به‌صورت job یک‌باره قبل از rollout نسخهٔ Backend اجرا می‌شود. برنامه هنگام startup schema را تغییر نمی‌دهد. استقرار تولیدی forward-only است؛ downgrade فقط در محیط دورریختنی و برای آزمون استفاده می‌شود.
