import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { ApiError, api } from "../../lib/api";
import type { TenantSummary } from "../auth/types";

export function TenantPicker() {
  const client = useQueryClient();
  const [name, setName] = useState("");
  const [currency, setCurrency] = useState<"IRT" | "IRR">("IRT");
  const [error, setError] = useState<string | null>(null);
  const tenants = useQuery({ queryKey: ["tenants"], queryFn: () => api.get<{ data: TenantSummary[] }>("/api/v1/tenants") });
  const activate = useMutation({
    mutationFn: (id: number) => api.post<void>(`/api/v1/tenants/${id}/activate`),
    onSuccess: async () => { await client.invalidateQueries(); },
    onError: () => setError("تغییر کسب‌وکار انجام نشد. دوباره تلاش کنید."),
  });
  const create = useMutation({
    mutationFn: () => api.post<{ data: TenantSummary }>("/api/v1/tenants", { name, currency_code: currency }),
    onSuccess: async () => { await client.invalidateQueries(); },
    onError: (cause: unknown) => setError(cause instanceof ApiError ? cause.message : "ساخت کسب‌وکار ناموفق بود."),
  });
  function submit(event: FormEvent<HTMLFormElement>) { event.preventDefault(); setError(null); create.mutate(); }

  if (tenants.isPending) return <p role="status" className="text-sm text-slate-500">در حال دریافت فهرست کسب‌وکارها…</p>;
  if (tenants.isError) return <p role="alert" className="text-sm text-red-700">دریافت کسب‌وکارها ناموفق بود. صفحه را دوباره بارگذاری کنید.</p>;
  return (
    <section className="mx-auto w-full max-w-lg rounded-2xl border border-slate-200 bg-white p-7 shadow-sm" dir="rtl">
      <h1 className="text-xl font-bold text-slate-900">انتخاب کسب‌وکار</h1>
      <p className="mt-2 text-sm text-slate-500">اطلاعات و گزارش‌ها در فضای کاری انتخاب‌شده نگهداری می‌شوند.</p>
      {tenants.data.data.length > 0 && <div className="mt-5 space-y-2">
        {tenants.data.data.map((tenant) => <button key={tenant.id} type="button" onClick={() => activate.mutate(tenant.id)} disabled={activate.isPending} className="flex w-full items-center justify-between rounded-lg border border-slate-200 px-4 py-3 text-right hover:border-teal-500 hover:bg-teal-50 disabled:opacity-60">
          <span><span className="block font-semibold text-slate-800">{tenant.name}</span><span className="mt-1 block text-xs text-slate-500">{tenant.role} · {tenant.currency_code}</span></span><span className="text-sm text-teal-700">انتخاب</span>
        </button>)}
      </div>}
      {tenants.data.data.length === 0 && <form className="mt-5 space-y-3" onSubmit={submit}>
        <label className="block text-sm font-medium text-slate-700">نام کسب‌وکار<input className="mt-1.5 w-full rounded-lg border border-slate-300 px-3 py-2.5" value={name} onChange={(event) => setName(event.target.value)} minLength={2} required /></label>
        <label className="block text-sm font-medium text-slate-700">واحد پول<select className="mt-1.5 w-full rounded-lg border border-slate-300 px-3 py-2.5" value={currency} onChange={(event) => setCurrency(event.target.value as "IRT" | "IRR")}><option value="IRT">تومان (IRT)</option><option value="IRR">ریال (IRR)</option></select></label>
        <button className="w-full rounded-lg bg-teal-700 px-4 py-3 font-semibold text-white disabled:opacity-60" type="submit" disabled={create.isPending}>ایجاد کسب‌وکار</button>
      </form>}
      {error && <p role="alert" className="mt-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
    </section>
  );
}
