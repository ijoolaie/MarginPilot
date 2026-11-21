import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { api, ApiError } from "../../lib/api";
import type { AuthMe } from "../auth/types";

type Supplier = { id: number; name: string; contact_name: string | null; phone: string | null; email: string | null; is_active: boolean };
type SupplierPage = { data: Supplier[]; meta: { page: number; page_size: number; total_items: number; total_pages: number } };

export function SuppliersPage() {
  const client = useQueryClient();
  const auth = client.getQueryData<AuthMe>(["auth", "me"]);
  const tenantId = auth?.active_tenant?.id;
  const canWrite = auth?.active_tenant?.permissions.includes("supplier:write") ?? false;
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [contact, setContact] = useState("");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const suppliers = useQuery({
    queryKey: ["suppliers", tenantId, query, page],
    queryFn: () => api.get<SupplierPage>(`/api/v1/suppliers?query=${encodeURIComponent(query)}&page=${page}&page_size=20`),
    enabled: tenantId !== undefined,
  });
  const create = useMutation({
    mutationFn: () => api.post<{ data: Supplier }>("/api/v1/suppliers", { name, contact_name: contact || null, phone: phone || null, email: email || null }),
    onSuccess: async () => {
      setShowForm(false); setName(""); setContact(""); setPhone(""); setEmail(""); setError(null); setPage(1);
      await client.invalidateQueries({ queryKey: ["suppliers", tenantId] });
    },
    onError: (cause: unknown) => setError(cause instanceof ApiError ? cause.message : "ثبت تأمین‌کننده ناموفق بود."),
  });
  function searchSubmit(event: FormEvent<HTMLFormElement>) { event.preventDefault(); setPage(1); setQuery(search.trim()); }
  function createSubmit(event: FormEvent<HTMLFormElement>) { event.preventDefault(); setError(null); create.mutate(); }

  return <section dir="rtl">
    <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-sm font-semibold text-teal-700">تأمین و خرید</p><h1 className="mt-1 text-2xl font-bold text-slate-900">تأمین‌کنندگان</h1><p className="mt-1 text-sm text-slate-500">اطلاعات تماس و وضعیت تأمین‌کنندگان</p></div>
      {canWrite && <button type="button" onClick={() => setShowForm((value) => !value)} className="rounded-lg bg-teal-700 px-4 py-2.5 text-sm font-semibold text-white hover:bg-teal-800">{showForm ? "بستن فرم" : "افزودن تأمین‌کننده"}</button>}
    </div>
    {showForm && <form className="mt-5 grid gap-3 rounded-xl border border-slate-200 bg-white p-5 sm:grid-cols-2" onSubmit={createSubmit}>
      <Field label="نام تأمین‌کننده" value={name} onChange={setName} required /><Field label="نام رابط" value={contact} onChange={setContact} /><Field label="تلفن" value={phone} onChange={setPhone} type="tel" /><Field label="ایمیل" value={email} onChange={setEmail} type="email" />
      {error && <p role="alert" className="sm:col-span-2 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
      <div className="sm:col-span-2"><button type="submit" disabled={create.isPending} className="rounded-lg bg-teal-700 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-60">{create.isPending ? "در حال ثبت…" : "ثبت تأمین‌کننده"}</button></div>
    </form>}
    <form className="mt-5 flex gap-2" onSubmit={searchSubmit}><input aria-label="جست‌وجوی تأمین‌کننده" className="min-w-0 flex-1 rounded-lg border border-slate-300 bg-white px-3 py-2.5" placeholder="جست‌وجو بر اساس نام، رابط، تلفن یا ایمیل" value={search} onChange={(event) => setSearch(event.target.value)} /><button className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium" type="submit">جست‌وجو</button></form>
    {suppliers.isPending ? <p role="status" className="mt-6 text-sm text-slate-500">در حال دریافت تأمین‌کنندگان…</p> : suppliers.isError ? <p role="alert" className="mt-6 text-sm text-red-700">دریافت تأمین‌کنندگان ناموفق بود.</p> : <>
      <div className="mt-4 overflow-x-auto rounded-xl border border-slate-200 bg-white"><table className="w-full min-w-[600px] text-right text-sm"><thead className="bg-slate-50 text-slate-600"><tr><th className="px-4 py-3">نام</th><th className="px-4 py-3">رابط</th><th className="px-4 py-3">تلفن</th><th className="px-4 py-3">ایمیل</th><th className="px-4 py-3">وضعیت</th></tr></thead><tbody className="divide-y divide-slate-100">{suppliers.data.data.map((supplier) => <tr key={supplier.id}><td className="px-4 py-3 font-medium text-slate-800">{supplier.name}</td><td className="px-4 py-3">{supplier.contact_name ?? "—"}</td><td className="px-4 py-3">{supplier.phone ?? "—"}</td><td className="px-4 py-3">{supplier.email ?? "—"}</td><td className="px-4 py-3">{supplier.is_active ? "فعال" : "غیرفعال"}</td></tr>)}</tbody></table>
      {suppliers.data.data.length === 0 && <p className="p-8 text-center text-sm text-slate-500">تأمین‌کننده‌ای برای نمایش وجود ندارد.</p>}</div>
      <div className="mt-4 flex items-center justify-between text-sm text-slate-500"><span>{suppliers.data.meta.total_items} تأمین‌کننده</span><div className="flex gap-2"><button type="button" disabled={page <= 1} onClick={() => setPage((value) => value - 1)} className="rounded border border-slate-300 px-3 py-1.5 disabled:opacity-40">قبلی</button><span className="py-1.5">صفحه {page} از {Math.max(1, suppliers.data.meta.total_pages)}</span><button type="button" disabled={page >= suppliers.data.meta.total_pages} onClick={() => setPage((value) => value + 1)} className="rounded border border-slate-300 px-3 py-1.5 disabled:opacity-40">بعدی</button></div></div>
    </>}
  </section>;
}

function Field({ label, value, onChange, required = false, type = "text" }: { label: string; value: string; onChange: (value: string) => void; required?: boolean; type?: string }) {
  return <label className="block text-sm font-medium text-slate-700">{label}<input className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2.5" type={type} value={value} onChange={(event) => onChange(event.target.value)} required={required} /></label>;
}
