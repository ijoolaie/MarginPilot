import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { ApiError, api, apiRequest } from "../../lib/api";
import type { AuthMe } from "../auth/types";

type ImportKind = "products" | "supplier_prices";
type ImportBatch = { id: number; kind: ImportKind; status: string; file_name: string; column_headers: string[]; mapping: Record<string, string | null>; stats: Record<string, number>; supplier_id: number | null; price_list_title: string | null; received_at: string | null };
type PreviewRow = { row_number: number; status: string; normalized: Record<string, unknown> | null; errors: Array<{ field: string; code: string; message_fa: string }> };
type Supplier = { id: number; name: string };
const fields: Record<ImportKind, Array<{ key: string; label: string; required: boolean }>> = {
  products: [
    { key: "sku", label: "شناسه کالا (SKU)", required: true }, { key: "name", label: "نام کالا", required: true }, { key: "unit", label: "واحد", required: true },
    { key: "description", label: "توضیحات", required: false }, { key: "sale_price", label: "قیمت فروش", required: false }, { key: "purchase_cost", label: "بهای خرید", required: false }, { key: "is_active", label: "وضعیت فعال", required: false },
  ],
  supplier_prices: [
    { key: "raw_name", label: "نام کالا در فایل تأمین‌کننده", required: true }, { key: "unit_price", label: "قیمت واحد", required: true }, { key: "unit", label: "واحد", required: true }, { key: "sku", label: "شناسه کالا (SKU)", required: false }, { key: "currency", label: "واحد پول", required: false },
  ],
};
const errorMessages: Record<string, string> = {
  IMPORT_KIND_NOT_READY: "ورود فایل فروش هنوز فعال نشده است.", SUPPLIER_REQUIRED: "تأمین‌کننده را انتخاب کنید.", RECEIVED_AT_REQUIRED: "تاریخ دریافت لیست قیمت الزامی است.",
  IMPORT_EXTENSION_NOT_ALLOWED: "فقط فایل CSV یا XLSX پذیرفته می‌شود.", IMPORT_EMPTY_FILE: "فایل خالی است.", IMPORT_NO_DATA_ROWS: "فایل ردیف داده ندارد.", UPLOAD_TOO_LARGE: "حجم فایل بیش از حد مجاز است.", IMPORT_MAPPING_REQUIRED: "نگاشت همه فیلدهای الزامی را تکمیل کنید.", IMPORT_MAPPING_DUPLICATE_COLUMN: "یک ستون فایل را به بیش از یک فیلد اختصاص ندهید.", IMPORT_STATE_INVALID: "وضعیت این واردسازی اجازه این عملیات را نمی‌دهد.", IMPORT_NO_VALID_ROWS: "هیچ ردیف معتبری برای ثبت وجود ندارد.",
};

export function ImportPage() {
  const client = useQueryClient();
  const auth = client.getQueryData<AuthMe>(["auth", "me"]);
  const tenantId = auth?.active_tenant?.id;
  const permissions = auth?.active_tenant?.permissions ?? [];
  const canExecute = permissions.includes("import:execute");
  const canReadSuppliers = permissions.includes("supplier:read");
  const [kind, setKind] = useState<ImportKind>("products");
  const [file, setFile] = useState<File | null>(null);
  const [supplierId, setSupplierId] = useState("");
  const [title, setTitle] = useState("");
  const [receivedAt, setReceivedAt] = useState("");
  const [batch, setBatch] = useState<ImportBatch | null>(null);
  const [mapping, setMapping] = useState<Record<string, string | null>>({});
  const [preview, setPreview] = useState<PreviewRow[]>([]);
  const [supplierPriceListId, setSupplierPriceListId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const suppliers = useQuery({
    queryKey: ["suppliers", tenantId, "import-options"],
    queryFn: () => api.get<{ data: Supplier[] }>("/api/v1/suppliers?page=1&page_size=100"),
    enabled: kind === "supplier_prices" && canReadSuppliers && tenantId !== undefined,
  });
  const upload = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error("FILE_REQUIRED");
      const body = new FormData();
      body.append("kind", kind); body.append("file", file);
      if (kind === "supplier_prices") {
        body.append("supplier_id", supplierId); body.append("price_list_title", title); body.append("received_at", receivedAt);
      }
      return apiRequest<{ data: ImportBatch }>("/api/v1/imports", { method: "POST", body });
    },
    onSuccess: ({ data }) => {
      setBatch(data); setPreview([]); setMapping(Object.fromEntries(fields[data.kind].map((field) => [field.key, data.column_headers.find((header) => header.trim().toLowerCase() === field.key) ?? null]))); setError(null);
    },
    onError: (cause: unknown) => setError(messageFor(cause)),
  });
  const mapImport = useMutation({
    mutationFn: () => apiRequest<{ data: ImportBatch; preview: PreviewRow[] }>(`/api/v1/imports/${batch?.id}/mapping`, { method: "PATCH", body: JSON.stringify({ mapping }) }),
    onSuccess: (result) => { setBatch(result.data); setPreview(result.preview); setError(null); },
    onError: (cause: unknown) => setError(messageFor(cause)),
  });
  const confirm = useMutation({
    mutationFn: () => apiRequest<{ data: { status: string; committed_rows: number; skipped_rows: number; supplier_price_list_id: number | null } }>(`/api/v1/imports/${batch?.id}/confirm`, { method: "POST", headers: { "Idempotency-Key": crypto.randomUUID() } }),
    onSuccess: (result) => { if (batch) setBatch({ ...batch, status: result.data.status, stats: { ...batch.stats, committed_rows: result.data.committed_rows, skipped_rows: result.data.skipped_rows } }); setSupplierPriceListId(result.data.supplier_price_list_id); setError(null); },
    onError: (cause: unknown) => setError(messageFor(cause)),
  });
  const finalizePriceList = useMutation({
    mutationFn: () => api.post<{ data: { id: number; status: string; item_count: number } }>(`/api/v1/price-lists/${supplierPriceListId}/finalize`, { confirm: true }),
    onSuccess: () => setError(null),
    onError: (cause: unknown) => setError(messageFor(cause)),
  });  const validRows = batch?.stats.valid_rows ?? 0;

  function uploadSubmit(event: FormEvent<HTMLFormElement>) { event.preventDefault(); setError(null); upload.mutate(); }
  function mappingSubmit(event: FormEvent<HTMLFormElement>) { event.preventDefault(); setError(null); mapImport.mutate(); }
  if (!canExecute) return <p role="alert" className="text-sm text-red-700" dir="rtl">مجوز واردسازی برای این حساب فعال نیست.</p>;

  return <section dir="rtl">
    <p className="text-sm font-semibold text-teal-700">ورود اطلاعات</p><h1 className="mt-1 text-2xl font-bold text-slate-900">واردسازی فایل</h1>
    <p className="mt-1 text-sm text-slate-500">ابتدا فایل بررسی می‌شود؛ هیچ داده‌ای پیش از تأیید نهایی ثبت نخواهد شد.</p>
    {!batch && <form className="mt-5 max-w-2xl space-y-4 rounded-xl border border-slate-200 bg-white p-5" onSubmit={uploadSubmit}>
      <label className="block text-sm font-medium text-slate-700">نوع اطلاعات<select className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2.5" value={kind} onChange={(event) => { setKind(event.target.value as ImportKind); setFile(null); }}><option value="products">کالاها</option>{canReadSuppliers && <option value="supplier_prices">قیمت تأمین‌کننده</option>}</select></label>
      {kind === "supplier_prices" && <>
        <label className="block text-sm font-medium text-slate-700">تأمین‌کننده<select className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2.5" value={supplierId} onChange={(event) => setSupplierId(event.target.value)} required><option value="">انتخاب تأمین‌کننده</option>{suppliers.data?.data.map((supplier) => <option key={supplier.id} value={supplier.id}>{supplier.name}</option>)}</select></label>
        <label className="block text-sm font-medium text-slate-700">عنوان لیست قیمت<input className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2.5" value={title} onChange={(event) => setTitle(event.target.value)} required /></label>
        <label className="block text-sm font-medium text-slate-700">تاریخ دریافت<input className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2.5" type="date" value={receivedAt} onChange={(event) => setReceivedAt(event.target.value)} required /></label>
      </>}
      <label className="block text-sm font-medium text-slate-700">فایل CSV یا XLSX<input className="mt-1 block w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-sm" type="file" accept=".csv,.xlsx" onChange={(event) => setFile(event.target.files?.[0] ?? null)} required /></label>
      {error && <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
      <button type="submit" disabled={!file || upload.isPending || (kind === "supplier_prices" && suppliers.isPending)} className="rounded-lg bg-teal-700 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50">{upload.isPending ? "در حال بارگذاری و بررسی…" : "بارگذاری و بررسی فایل"}</button>
    </form>}
    {batch && <div className="mt-5 space-y-5">
      <div className="rounded-xl border border-slate-200 bg-white p-5"><div className="flex flex-wrap items-center justify-between gap-2"><h2 className="font-semibold text-slate-900">{batch.file_name}</h2><span className="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-700">{statusLabel(batch.status)}</span></div><p className="mt-2 text-sm text-slate-500">شناسه واردسازی: {batch.id} · ردیف‌ها: {batch.stats.total_rows ?? 0}</p></div>
      {batch.status !== "committed" && <form className="rounded-xl border border-slate-200 bg-white p-5" onSubmit={mappingSubmit}>
        <h2 className="font-semibold text-slate-900">نگاشت ستون‌ها</h2><p className="mt-1 text-sm text-slate-500">برای هر فیلد، ستون متناظر فایل را انتخاب کنید. موارد ستاره‌دار الزامی‌اند.</p>
        <div className="mt-4 grid gap-3 sm:grid-cols-2">{fields[batch.kind].map((field) => <label key={field.key} className="block text-sm font-medium text-slate-700">{field.label}{field.required ? " *" : ""}<select className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5" value={mapping[field.key] ?? ""} onChange={(event) => setMapping((current) => ({ ...current, [field.key]: event.target.value || null }))}><option value="">بدون نگاشت</option>{batch.column_headers.map((header) => <option key={header} value={header}>{header}</option>)}</select></label>)}</div>
        {error && <p role="alert" className="mt-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
        <button type="submit" disabled={mapImport.isPending} className="mt-4 rounded-lg bg-teal-700 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50">{mapImport.isPending ? "در حال اعتبارسنجی…" : "اعتبارسنجی و پیش‌نمایش"}</button>
      </form>}
      {preview.length > 0 && <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white p-5"><div className="flex flex-wrap items-center justify-between gap-2"><h2 className="font-semibold text-slate-900">پیش‌نمایش ردیف‌ها</h2><p className="text-sm text-slate-500">معتبر: {validRows} · خطا/تکراری: {preview.length - validRows}</p></div><table className="mt-4 w-full min-w-[600px] text-right text-sm"><thead className="bg-slate-50"><tr><th className="px-3 py-2">ردیف</th><th className="px-3 py-2">وضعیت</th><th className="px-3 py-2">داده نرمال‌شده</th><th className="px-3 py-2">خطاها</th></tr></thead><tbody className="divide-y divide-slate-100">{preview.map((row) => <tr key={row.row_number}><td className="px-3 py-2">{row.row_number}</td><td className="px-3 py-2">{row.status === "valid" ? "معتبر" : row.status === "duplicate" ? "تکراری" : "خطا"}</td><td className="max-w-sm px-3 py-2 text-xs">{row.normalized ? Object.entries(row.normalized).map(([key, value]) => `${key}: ${String(value)}`).join(" · ") : "—"}</td><td className="px-3 py-2 text-xs text-red-700">{row.errors.map((item) => item.message_fa).join("؛ ") || "—"}</td></tr>)}</tbody></table></div>}
      {batch.status === "awaiting_confirmation" && <div className="rounded-xl border border-amber-200 bg-amber-50 p-5">{error && <p role="alert" className="mb-3 text-sm text-red-700">{error}</p>}<p className="text-sm text-amber-900">تأیید نهایی فقط ردیف‌های معتبر را ثبت می‌کند؛ ردیف‌های خطادار و تکراری کنار گذاشته می‌شوند.</p><button type="button" onClick={() => confirm.mutate()} disabled={confirm.isPending || validRows === 0} className="mt-3 rounded-lg bg-teal-700 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50">{confirm.isPending ? "در حال ثبت اتمیک…" : `تأیید و ثبت ${validRows} ردیف معتبر`}</button></div>}
            {batch.status === "committed" && <div className="rounded-xl bg-emerald-50 p-5 text-sm text-emerald-800"><p role="status">واردسازی ثبت شد. تعداد ردیف‌های ثبت‌شده: {batch.stats.committed_rows ?? 0}.</p>{supplierPriceListId !== null && !finalizePriceList.isSuccess && <div className="mt-3">{error && <p role="alert" className="mb-2 text-sm text-red-700">{error}</p>}<p>لیست قیمت به‌صورت پیش‌نویس ساخته شده است و تا نهایی‌سازی در مقایسه‌ها استفاده نمی‌شود.</p><button type="button" onClick={() => finalizePriceList.mutate()} disabled={finalizePriceList.isPending} className="mt-2 rounded-lg bg-teal-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">{finalizePriceList.isPending ? "در حال نهایی‌سازی…" : "نهایی‌سازی لیست قیمت"}</button></div>}</div>}
      {finalizePriceList.isSuccess && <p role="status" className="rounded-lg bg-emerald-50 px-4 py-3 text-sm text-emerald-800">لیست قیمت نهایی شد و آماده مقایسه است.</p>}
      <button type="button" onClick={() => { setBatch(null); setPreview([]); setMapping({}); setSupplierPriceListId(null); setError(null); setFile(null); }} className="text-sm font-medium text-teal-700 hover:underline">شروع واردسازی جدید</button>
    </div>}
  </section>;
}

function messageFor(cause: unknown): string {
  if (cause instanceof ApiError) return errorMessages[cause.code] ?? cause.message;
  return "عملیات واردسازی ناموفق بود. دوباره تلاش کنید.";
}
function statusLabel(status: string): string {
  const labels: Record<string, string> = { parsed: "فایل بارگذاری شد", mapped: "نگاشت انجام شد", validated: "اعتبارسنجی شد", awaiting_confirmation: "منتظر تأیید", committed: "ثبت‌شده", failed: "ناموفق", cancelled: "لغوشده" };
  return labels[status] ?? status;
}




