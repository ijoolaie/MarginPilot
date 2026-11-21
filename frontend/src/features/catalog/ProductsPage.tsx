import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { api, ApiError } from "../../lib/api";
import type { AuthMe, TenantSummary } from "../auth/types";

type Product = { id: number; sku: string; name: string; unit: string; sale_price: string | number | null; purchase_cost: string | number | null; is_active: boolean };
type ProductPage = { data: Product[]; meta: { page: number; page_size: number; total_items: number; total_pages: number } };
const units: Record<string, string> = { piece: "عدد", kg: "کیلوگرم", liter: "لیتر", meter: "متر", box: "جعبه" };

export function ProductsPage() {
  const client = useQueryClient();
  const auth = client.getQueryData<AuthMe>(["auth", "me"]);
  const tenantId = auth?.active_tenant?.id;
  const tenantRows = client.getQueryData<{ data: TenantSummary[] }>(["tenants"]);
  const currency = tenantRows?.data.find((tenant) => tenant.id === tenantId)?.currency_code;
  const canWrite = auth?.active_tenant?.permissions.includes("product:write") ?? false;
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [showForm, setShowForm] = useState(false);
  const [sku, setSku] = useState("");
  const [name, setName] = useState("");
  const [unit, setUnit] = useState("piece");
  const [salePrice, setSalePrice] = useState("");
  const [purchaseCost, setPurchaseCost] = useState("");
  const [error, setError] = useState<string | null>(null);
  const products = useQuery({
    queryKey: ["products", tenantId, query, page],
    queryFn: () => api.get<ProductPage>(`/api/v1/products?query=${encodeURIComponent(query)}&page=${page}&page_size=20`),
    enabled: tenantId !== undefined,
  });
  const create = useMutation({
    mutationFn: () => api.post<{ data: Product }>("/api/v1/products", { sku, name, unit, sale_price: salePrice || null, purchase_cost: purchaseCost || null }),
    onSuccess: async () => {
      setShowForm(false); setSku(""); setName(""); setSalePrice(""); setPurchaseCost(""); setError(null); setPage(1);
      await client.invalidateQueries({ queryKey: ["products", tenantId] });
    },
    onError: (cause: unknown) => setError(cause instanceof ApiError ? cause.message : "ثبت کالا ناموفق بود."),
  });
  function searchSubmit(event: FormEvent<HTMLFormElement>) { event.preventDefault(); setPage(1); setQuery(search.trim()); }
  function createSubmit(event: FormEvent<HTMLFormElement>) { event.preventDefault(); setError(null); create.mutate(); }

  return <section dir="rtl">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><p className="text-sm font-semibold text-teal-700">کاتالوگ</p><h1 className="mt-1 text-2xl font-bold text-slate-900">کالاها</h1><p className="mt-1 text-sm text-slate-500">مدیریت اطلاعات پایه و قیمت مرجع کالاها</p></div>
      {canWrite && <button type="button" onClick={() => setShowForm((value) => !value)} className="rounded-lg bg-teal-700 px-4 py-2.5 text-sm font-semibold text-white hover:bg-teal-800">{showForm ? "بستن فرم" : "افزودن کالا"}</button>}
    </div>
    {showForm && <form className="mt-5 grid gap-3 rounded-xl border border-slate-200 bg-white p-5 sm:grid-cols-2" onSubmit={createSubmit}>
      <Field label="کد کالا (SKU)" value={sku} onChange={setSku} required />
      <Field label="نام کالا" value={name} onChange={setName} required />
      <label className="block text-sm font-medium text-slate-700">واحد<select className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2.5" value={unit} onChange={(event) => setUnit(event.target.value)}>{Object.entries(units).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
      <Field label="قیمت فروش" value={salePrice} onChange={setSalePrice} type="number" min="0" step="0.01" />
      <Field label="بهای خرید مرجع" value={purchaseCost} onChange={setPurchaseCost} type="number" min="0" step="0.01" />
      {error && <p role="alert" className="sm:col-span-2 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
      <div className="sm:col-span-2"><button type="submit" disabled={create.isPending} className="rounded-lg bg-teal-700 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-60">{create.isPending ? "در حال ثبت…" : "ثبت کالا"}</button></div>
    </form>}
    <form className="mt-5 flex gap-2" onSubmit={searchSubmit}><input aria-label="جست‌وجوی کالا" className="min-w-0 flex-1 rounded-lg border border-slate-300 bg-white px-3 py-2.5" placeholder="جست‌وجو بر اساس نام یا SKU" value={search} onChange={(event) => setSearch(event.target.value)} /><button className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium" type="submit">جست‌وجو</button></form>
    {products.isPending ? <p role="status" className="mt-6 text-sm text-slate-500">در حال دریافت کالاها…</p> : products.isError ? <p role="alert" className="mt-6 text-sm text-red-700">دریافت کالاها ناموفق بود.</p> : <>
      <div className="mt-4 overflow-x-auto rounded-xl border border-slate-200 bg-white"><table className="w-full min-w-[680px] text-right text-sm"><thead className="bg-slate-50 text-slate-600"><tr><th className="px-4 py-3">کد کالا</th><th className="px-4 py-3">نام کالا</th><th className="px-4 py-3">واحد</th><th className="px-4 py-3">قیمت فروش{currency ? ` (${currency})` : ""}</th><th className="px-4 py-3">بهای خرید{currency ? ` (${currency})` : ""}</th><th className="px-4 py-3">وضعیت</th></tr></thead><tbody className="divide-y divide-slate-100">{products.data.data.map((product) => <tr key={product.id}><td className="px-4 py-3 font-mono text-xs">{product.sku}</td><td className="px-4 py-3 font-medium text-slate-800">{product.name}</td><td className="px-4 py-3">{units[product.unit] ?? product.unit}</td><td className="px-4 py-3 tabular-nums">{product.sale_price ?? "—"}</td><td className="px-4 py-3 tabular-nums">{product.purchase_cost ?? "—"}</td><td className="px-4 py-3">{product.is_active ? "فعال" : "غیرفعال"}</td></tr>)}</tbody></table>
      {products.data.data.length === 0 && <p className="p-8 text-center text-sm text-slate-500">کالایی برای نمایش وجود ندارد.</p>}</div>
      <div className="mt-4 flex items-center justify-between text-sm text-slate-500"><span>{products.data.meta.total_items} کالا</span><div className="flex gap-2"><button type="button" disabled={page <= 1} onClick={() => setPage((value) => value - 1)} className="rounded border border-slate-300 px-3 py-1.5 disabled:opacity-40">قبلی</button><span className="py-1.5">صفحه {page} از {Math.max(1, products.data.meta.total_pages)}</span><button type="button" disabled={page >= products.data.meta.total_pages} onClick={() => setPage((value) => value + 1)} className="rounded border border-slate-300 px-3 py-1.5 disabled:opacity-40">بعدی</button></div></div>
    </>}
  </section>;
}

function Field({ label, value, onChange, required = false, type = "text", min, step }: { label: string; value: string; onChange: (value: string) => void; required?: boolean; type?: string; min?: string; step?: string }) {
  return <label className="block text-sm font-medium text-slate-700">{label}<input className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2.5" type={type} value={value} onChange={(event) => onChange(event.target.value)} required={required} min={min} step={step} /></label>;
}


