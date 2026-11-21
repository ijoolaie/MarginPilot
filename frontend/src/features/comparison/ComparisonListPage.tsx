import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { ApiError, apiRequest, api } from "../../lib/api";
import type { AuthMe } from "../auth/types";

type Supplier = { id: number; name: string };
type PriceList = { id: number; title: string; received_at: string; status: string };
type Run = { id: number; base_list_id: number; target_list_id: number; match_strategy: string; status: string; summary: Record<string, number>; created_at: string };

export function ComparisonListPage() {
  const client = useQueryClient();
  const navigate = useNavigate();
  const auth = client.getQueryData<AuthMe>(["auth", "me"]);
  const tenantId = auth?.active_tenant?.id;
  const canWrite = auth?.active_tenant?.permissions.includes("comparison:write") ?? false;
  const [baseSupplier, setBaseSupplier] = useState("");
  const [targetSupplier, setTargetSupplier] = useState("");
  const [baseList, setBaseList] = useState("");
  const [targetList, setTargetList] = useState("");
  const [strategy, setStrategy] = useState("sku_then_name");
  const [error, setError] = useState<string | null>(null);
  const suppliers = useQuery({ queryKey: ["suppliers", tenantId, "comparison"], queryFn: () => api.get<{ data: Supplier[] }>("/api/v1/suppliers?page=1&page_size=100"), enabled: tenantId !== undefined });
  const baseLists = useQuery({ queryKey: ["price-lists", tenantId, baseSupplier], queryFn: () => api.get<{ data: PriceList[] }>(`/api/v1/suppliers/${baseSupplier}/price-lists?page=1&page_size=100`), enabled: Boolean(baseSupplier) });
  const targetLists = useQuery({ queryKey: ["price-lists", tenantId, targetSupplier], queryFn: () => api.get<{ data: PriceList[] }>(`/api/v1/suppliers/${targetSupplier}/price-lists?page=1&page_size=100`), enabled: Boolean(targetSupplier) });
  const runs = useQuery({ queryKey: ["comparisons", tenantId], queryFn: () => api.get<{ data: Run[] }>("/api/v1/comparison/runs?page=1&page_size=25"), enabled: tenantId !== undefined });
  const create = useMutation({
    mutationFn: () => apiRequest<{ data: Run & { pending_matches: number } }>("/api/v1/comparison/runs", { method: "POST", headers: { "Idempotency-Key": crypto.randomUUID() }, body: JSON.stringify({ base_list_id: Number(baseList), target_list_id: Number(targetList), match_strategy: strategy }) }),
    onSuccess: async (result) => { setError(null); await client.invalidateQueries({ queryKey: ["comparisons", tenantId] }); await navigate(`/comparison/${result.data.id}`); },
    onError: (cause: unknown) => setError(cause instanceof ApiError ? cause.message : "ایجاد مقایسه ناموفق بود."),
  });
  const finalBase = (baseLists.data?.data ?? []).filter((item) => item.status === "final");
  const finalTarget = (targetLists.data?.data ?? []).filter((item) => item.status === "final");
  const sameList = baseList !== "" && baseList === targetList;

  return <section dir="rtl">
    <p className="text-sm font-semibold text-teal-700">تحلیل تأمین</p><h1 className="mt-1 text-2xl font-bold text-slate-900">مقایسه قیمت تأمین‌کنندگان</h1>
    <p className="mt-1 text-sm text-slate-500">فقط لیست‌های قیمت نهایی‌شده و هم‌واحد پول قابل مقایسه‌اند.</p>
    {canWrite && <div className="mt-5 rounded-xl border border-slate-200 bg-white p-5"><h2 className="font-semibold text-slate-900">مقایسه جدید</h2>
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <label className="block text-sm font-medium text-slate-700">تأمین‌کننده مبنا<select className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2.5" value={baseSupplier} onChange={(event) => { setBaseSupplier(event.target.value); setBaseList(""); }}><option value="">انتخاب کنید</option>{suppliers.data?.data.map((supplier) => <option key={supplier.id} value={supplier.id}>{supplier.name}</option>)}</select></label>
        <label className="block text-sm font-medium text-slate-700">تأمین‌کننده هدف<select className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2.5" value={targetSupplier} onChange={(event) => { setTargetSupplier(event.target.value); setTargetList(""); }}><option value="">انتخاب کنید</option>{suppliers.data?.data.map((supplier) => <option key={supplier.id} value={supplier.id}>{supplier.name}</option>)}</select></label>
        <label className="block text-sm font-medium text-slate-700">لیست قیمت مبنا<select className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2.5" value={baseList} onChange={(event) => setBaseList(event.target.value)} disabled={!baseSupplier}><option value="">انتخاب لیست نهایی</option>{finalBase.map((item) => <option key={item.id} value={item.id}>{item.title} · {item.received_at}</option>)}</select></label>
        <label className="block text-sm font-medium text-slate-700">لیست قیمت هدف<select className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2.5" value={targetList} onChange={(event) => setTargetList(event.target.value)} disabled={!targetSupplier}><option value="">انتخاب لیست نهایی</option>{finalTarget.map((item) => <option key={item.id} value={item.id}>{item.title} · {item.received_at}</option>)}</select></label>
        <label className="block text-sm font-medium text-slate-700 sm:col-span-2">روش تطبیق<select className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2.5" value={strategy} onChange={(event) => setStrategy(event.target.value)}><option value="sku_then_name">ابتدا SKU، سپس نام نرمال‌شده</option><option value="sku">فقط SKU</option><option value="normalized_name">فقط نام نرمال‌شده</option></select></label>
      </div>
      {error && <p role="alert" className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
      <button type="button" disabled={!baseList || !targetList || sameList || create.isPending} onClick={() => create.mutate()} className="mt-4 rounded-lg bg-teal-700 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50">{create.isPending ? "در حال مقایسه…" : "ایجاد مقایسه"}</button>
    </div>}
    {suppliers.isError && <p role="alert" className="mt-4 text-sm text-red-700">دریافت تأمین‌کنندگان ناموفق بود.</p>}
    {(baseLists.isError || targetLists.isError) && <p role="alert" className="mt-4 text-sm text-red-700">دریافت لیست‌های قیمت ناموفق بود.</p>}
    <h2 className="mt-8 font-semibold text-slate-900">مقایسه‌های قبلی</h2>
    {runs.isPending ? <p role="status" className="mt-3 text-sm text-slate-500">در حال دریافت مقایسه‌ها…</p> : runs.isError ? <p role="alert" className="mt-3 text-sm text-red-700">دریافت سوابق مقایسه ناموفق بود.</p> : <div className="mt-3 overflow-x-auto rounded-xl border border-slate-200 bg-white"><table className="w-full min-w-[650px] text-right text-sm"><thead className="bg-slate-50"><tr><th className="px-4 py-3">شناسه</th><th className="px-4 py-3">روش</th><th className="px-4 py-3">تعداد تطبیق</th><th className="px-4 py-3">نیازمند بررسی</th><th className="px-4 py-3">وضعیت</th><th className="px-4 py-3">جزئیات</th></tr></thead><tbody className="divide-y divide-slate-100">{runs.data.data.map((run) => <tr key={run.id}><td className="px-4 py-3">{run.id}</td><td className="px-4 py-3">{strategyLabel(run.match_strategy)}</td><td className="px-4 py-3">{run.summary.total_matches ?? 0}</td><td className="px-4 py-3">{run.summary.uncertain ?? 0}</td><td className="px-4 py-3">{run.status === "completed" ? "تکمیل‌شده" : "نیازمند تأیید"}</td><td className="px-4 py-3"><Link className="font-semibold text-teal-700 hover:underline" to={`/comparison/${run.id}`}>مشاهده</Link></td></tr>)}</tbody></table>{runs.data.data.length === 0 && <p className="p-7 text-center text-sm text-slate-500">هنوز مقایسه‌ای ثبت نشده است.</p>}</div>}
  </section>;
}
function strategyLabel(value: string) { return value === "sku" ? "SKU" : value === "normalized_name" ? "نام" : "SKU و نام"; }


