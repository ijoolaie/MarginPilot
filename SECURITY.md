# SECURITY — MarginPilot

این سند وضعیت امنیت پیاده‌سازی‌شده در هر مرحله را ثبت می‌کند. مرجع طراحی کامل: [docs/security.md](docs/security.md) (OWASP Top 10 / ASVS L2).

## وضعیت فعلی — Phase 2 / Step 1 (زیرساخت)

### پیاده‌سازی‌شده و راستی‌آزمایی‌شده در این مرحله

| کنترل | وضعیت |
|---|---|
| اجرای Backend با کاربر غیر root در image | ✅ (`Dockerfile`: user اختصاصی marginpilot) |
| اجرای Frontend با سرور non-root | ✅ (nginx-unprivileged، پورت 8080) |
| پورت PostgreSQL بسته به بیرون | ✅ (compose: بدون `ports`؛ فقط شبکهٔ داخلی) |
| Backend غیرقابل دسترسی مستقیم از اینترنت | ✅ (compose: بدون `ports`؛ فقط Caddy نقطهٔ ورود) |
| Secrets خارج از کد/image/ریپو | ✅ (`.env` gitignored + `.dockerignore`؛ compose از env می‌خواند؛ `.env.example` بدون مقدار واقعی) |
| Pin نسخه‌ها + lock با hash | ✅ (backend: exact + ۸۵۳ خط hash با `--require-hashes`؛ frontend: exact + package-lock؛ imageها با digest) |
| اسکن وابستگی‌ها | ✅ اجرا شد: `pip-audit` (پس از bump دو CVE → پاک)، `npm audit` (0)؛ `gitleaks` فقط به‌صورت گیت CI تعریف شده |
| Security headers | ✅ در FastAPI (`nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, `CSP`, `Permissions-Policy`) + Caddy (`-Server`, headers) |
| عدم افشای جزئیات داخلی در خطا | ✅ (Error Schema یکسان؛ 500 بدون جزئیات؛ تست unit دارد؛ جزئیات فقط در لاگ با request_id) |
| عدم ثبت secret در لاگ | ✅ (فیلدهای لاگ whitelist؛ DSN هرگز لاگ نمی‌شود؛ تست‌های unit بدنهٔ پاسخ health را بررسی می‌کنند) |
| docs API غیرفعال در production | ✅ (`APP_ENV=production` → docs/openapi خاموش) |
| fail-fast پیکربندی | ✅ (اسکیم DATABASE_URL، placeholder password، مقادیر نامعتبر → توقف startup؛ تست unit دارد) |

### تعریف‌شده اما هنوز اجرا نشده

- `gitleaks` در CI: فقط فایل workflow ساخته شده (CI هنوز اجرا نشده — Step 1 فقط فایل را تحویل می‌دهد).
- `docker compose up` کامل: در سندباکس daemon وجود ندارد؛ اجرای واقعی در CI/محلی شما انجام می‌شود.
- احراز هویت، CSRF، RBAC، Tenant Isolation، rate limit، Audit: طبق roadmap از Phase 3 (docs/security.md) — **در این مرحله هیچ‌کدام پیاده نشده و ادعایی هم نیست.**

### گزارش‌گیری مسئولانه

اگر مشکل امنیتی در این مخزن می‌بینید، Issue عمومی باز نکنید؛ با owner مخزن تماس بگیرید. (کانال رسمی گزارش در فاز استقرار مستند می‌شود.)
