# وابستگی‌ها و سیاست نسخه‌گذاری — MarginPilot

**وضعیت (Phase 2 / Step 1):** ماتریس سازگاری واقعاً اجرا شد؛ نسخه‌های ستون «Pinned» **آزمایش‌شده**اند (نصب clean، build، تست دود — شواهد: `download/evidence/`). استعلام اولیهٔ ۲۰۲۶-۱۱-۱۶ صرفاً نقطهٔ شروع بود و همان‌طور که شرط این سند بود، بدون آزمایش pin نشد. دو یافتهٔ امنیتی audit (CVE) باعث انحراف از «آخرین registry» شد که پایین مستند است.

## ۱) سیاست

1. نسخه‌ها **exact pin** می‌شوند (بدون `^`/`~`) در lock file رسمی هر سمت (backend: `requirements.lock` با hash کامل + `requirements-runtime.lock` برای image؛ frontend: `package.json` exact + `package-lock.json`).
2. قبل از pin، **ماتریس سازگاری** هر خانواده چک می‌شود؛ صرفاً «جدیدترین» انتخاب نمی‌شود (شرط ۶ شما) — دو مورد نقض این شدند و دلیل مستند دارند.
3. ارتقا فقط از طریق PR با اجرای کامل CI؛ ارتقای امنیتی (CVE) با اولویت — در همین مرحله اعمال شد (پایین).
4. اسکن خودکار: `pip-audit` و `npm audit` + `gitleaks` در CI از Phase 2.

## ۲) نتایج ماتریس سازگاری (آزمایش واقعی — ۲۰۲۶-۱۱-۱۶)

| خانواده | نتیجهٔ آزمایش | تصمیم |
|---|---|---|
| TypeScript 7 + Vite 8 | ❌ `npm install` کل ماتریس با TS 7.0.2 **شکست خورد** (ERESOLVE): `peer typescript@">=4.8.4 <6.1.0" from typescript-eslint@8.73.0` — شواهد: evidence/frontend_matrix_smoke.txt | TS **6.0.3** (داخل بازهٔ peer، تایپ‌چک/build/vitest سبز) |
| React 19 + @tanstack/react-query 5 | ✅ نصب + smoke | React 19.3.1 + RQ 5.107.1 |
| react-hook-form 7 + resolvers + Zod 4 | ✅ type-check و resolver روی schema واقعی | 7.92.0 / 7.0.6 / 4.6.7 |
| Tailwind 4 + Vite | ✅ build با `@tailwindcss/vite` و RTL | 4.3.5 (هر دو بسته) |
| ECharts 6 + React 19 | ✅ build (هشدار اندازهٔ chunk — بی‌خطر؛ code-split در فاز نمودار) | 6.1.0 |
| @playwright/test 1.65 | ✅ بسته نصب شد؛ دانلود مرورگر به فاز E2E موکول (کش sandbox: Chromium rev 1200 = playwright 1.57) | 1.65.1 |
| react-router 8.5.1 (جدیدترین) | ریسک: major چندروزه در مرحلهٔ foundation | **7.18.5** انتخاب شد؛ ارتقا به 8 با تست کامل در PR جداگانه |

## ۳) Backend — نسخه‌های نهایی آزمایش‌شده

| بسته | Pinned | دلیل انحراف از آخرین registry |
|---|---|---|
| fastapi | 0.163.1 | — |
| uvicorn | 0.54.0 | — |
| pydantic | 2.12.5 | — |
| pydantic-settings | **2.14.2** | ⚠️ امنیتی: registry-latest 2.13.1 با `pip-audit` → **CVE-2026-58203**؛ bump به نسخهٔ fix |
| SQLAlchemy | 2.1.8 | — |
| alembic | 1.20.1 | — (در deps هست؛ migration از Phase 3) |
| psycopg / psycopg-binary | 3.3.9 | — |
| httpx | 0.28.1 | — |
| pytest | **9.0.3** | ⚠️ امنیتی: 9.0.2 → **PYSEC-2026-1845**؛ bump به نسخهٔ fix |
| pytest-asyncio / pytest-cov | 1.3.0 / 7.0.0 | — |
| ruff / mypy | 0.17.5 / 2.4.1 | — |

Lock files: `backend/requirements.lock` (۳۸ بسته، ۸۵۳ hash) و `backend/requirements-runtime.lock` (۲۲ بسته، ۴۴۶ hash، فقط runtime برای image). شمارش رسمی (P2-06): خطوط `name==version` بدون کامنت‌ها با regex `^[A-Za-z0-9][A-Za-z0-9._-]*==`. نصب clean از lock با `--require-hashes` در venv تازه تأیید شد. **یافتهٔ محیطی:** منبع env پیش‌فرض pydantic-settings در سندباکس با هیچ نسخه‌ای (2.12.0/2.13.1/2.16.3) مقدار برنمی‌گرداند (شواهد: evidence/pydantic_settings_repro.txt) → بارگذاری env به‌صورت صریح با init kwargs انجام می‌شود؛ قرارداد env var و .env یکسان است و در CI با همان تست‌ها بازآزمایی می‌شود.

## ۴) Frontend — نسخه‌های نهایی آزمایش‌شده

| بسته | Pinned | یادداشت |
|---|---|---|
| react / react-dom | 19.3.1 | — |
| vite / @vitejs/plugin-react | 8.3.8 / 6.3.0 | — |
| typescript | **6.0.3** | TS 7 رد شد (ماتریس §۲) |
| tailwindcss / @tailwindcss/vite | 4.3.5 / 4.3.5 | — |
| @tanstack/react-query | 5.107.1 | — |
| react-router | **7.18.5** | 8.5.1 معلق — §۲ |
| vazirmatn | 33.0.3 | self-host از طریق بسته (woff2 در build باندل می‌شود) |
| vitest / jsdom / @testing-library/react (+dom) | 5.1.0 / 31.0.1 / 16.3.3 / 10.4.2 | — |
| eslint / typescript-eslint / react-hooks / react-refresh / globals | 10.15.0 / 8.73.0 / 7.1.1 / 0.5.8 / 17.14.0 | برای گیت lint الزامی CI اضافه شدند |
| react-hook-form / @hookform/resolvers / zod / echarts / @playwright/test | 7.92.0 / 7.0.6 / 4.6.7 / 6.1.0 / 1.65.1 | **ماتریس‌آزموده**؛ مصرف‌کنندهٔ محصولی از فاز بعد — طبق قاعدهٔ «بدون وابستگی بی‌مصرف» در package.json اصلی نیستند، فقط در smoke ماتریس آزمایش شدند |

Frontend: `package.json` exact + `package-lock.json`؛ `npm ci` در محیط تمیز موفق. `npm audit`: 0 vulnerabilities.

## ۵) Infrastructure — تصاویر Docker (تگ تأییدشده + digest)

هر تگ با Docker Registry HTTP API راستی‌آزمایی شد (تگ واقعاً موجود است؛ بدون نیاز به daemon) — شواهد: `download/evidence/image_digests.json`.

| image | tag | digest |
|---|---|---|
| python | 3.12-slim-bookworm | `sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df` |
| node | 24-alpine | `sha256:116b800c3754b440ee0aa3ed2f20f5bf3d99a554bfd9adeea09ea8017f6e85f5` |
| nginxinc/nginx-unprivileged | 1.29-alpine | `sha256:0c79d56aee561a1d81c63f00eee5fb5fe29279560cdc55e91425133104c7fbe6` |
| postgres | 16-alpine | `sha256:81e77a4833487b8132fe4b00bedd39dc3f74b8641e387f19312a48f7de218c2e` |
| caddy | 2-alpine | `sha256:003a97808e781aa9f7e75cc2f43d34d461099031faf5e20faefb9f61126836f0` |

CI: GitHub Actions (ubuntu-latest) + سرویس PostgreSQL واقعی (`postgres:16-alpine`) برای integration.

در v1 اضافه نمی‌شوند: polars، celery، redis-server (فقط fakeredis برای تست)، هر AI SDK، PyJWT (بازیابی رمز با توکن تصادفی یک‌بارمصرف — ADR-003 به‌روزرسانی‌شده؛ بدون JWT در کل v1).
