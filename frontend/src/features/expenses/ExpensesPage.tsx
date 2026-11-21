import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { ApiError, api, apiRequest } from "../../lib/api";
import type { AuthMe, TenantSummary } from "../auth/types";

type Expense = { id: number; expense_date: string; type: string; amount: string; currency: string; description: string | null; allocation_scope: string; order_id: number | null; product_id: number | null; period_start: string | null; period_end: string | null; allocation_strategy: string | null };
type Order = { id: number; order_number: string; order_date: string; status: string };
type Product = { id: number; name: string; sku: string };
type ExpensePage = { data: Expense[]; pagination: { page: number; pages: number; total: number } };
const expenseTypes = [{ value: "shipping", label: "حمل‌ونقل" }, { value: "packaging", label: "بسته‌بندی" }, { value: "advertising", label: "تبلیغات" }, { value: "payment_fee", label: "کارمزد پرداخت" }, { value: "operational", label: "عملیاتی" }, { value: "other", label: "سایر" }];
const scopes = [{ value: "order", label: "سفارش مشخص" }, { value: "product", label: "کالای مشخص" }, { value: "period", label: "دوره زمانی" }];
const strategies = [{ value: "revenue_share", label: "سهم از درآمد" }, { value: "equal_quantity", label: "برابر بر اساس تعداد" }, { value: "equal_count", label: "برابر بین کالاها" }];

export function ExpensesPage() {
  const client = useQueryClient();
  const auth = client.getQueryData<AuthMe>(["auth", "me"]);
  const tenantId = auth?.active_tenant?.id;
  const canWrite = auth?.active_tenant?.permissions.includes("expense:write") ?? false;
  const tenantRows = client.getQueryData<{ data: TenantSummary[] }>(["tenants"]);
  const currency = tenantRows?.data.find((tenant) => tenant.id === tenantId)?.currency_code;
  const [showForm, setShowForm] = useState(false);
  const [date, setDate] = useState("");
  const [type, setType] = useState("operational");
  const [amount, setAmount] = useState("");
  const [description, setDescription] = useState("");
  const [scope, setScope] = useState("period");
  const [orderId, setOrderId] = useState("");
  const [productId, setProductId] = useState("");
  const [periodStart, setPeriodStart] = useState("");
  const [periodEnd, setPeriodEnd] = useState("");
  const [strategy, setStrategy] = useState("revenue_share");
  const [error, setError] = useState<string | null>(null);
  const expenses = useQuery({ queryKey: ["expenses", tenantId], queryFn: () => api.get<ExpensePage>("/api/v1/expenses?page=1&page_size=50"), enabled: tenantId !== undefined });
  const orders = useQuery({ queryKey: ["sales-orders", tenantId, "expense-options"], queryFn: () => api.get<{ data: Order[] }>("/api/v1/sales/orders?page=1&page_size=100"), enabled: showForm && scope === "order" && tenantId !== undefined });
  const products = useQuery({ queryKey: ["products", tenantId, "expense-options"], queryFn: () => api.get<{ data: Product[] }>("/api/v1/products?page=1&page_size=100"), enabled: showForm && scope === "product" && tenantId !== undefined });
  const create = useMutation({
    mutationFn: () => api.post<{ data: Expense }>("/api/v1/expenses", { expense_date: date, type, amount, currency, description: description || null, allocation_scope: scope, order_id: scope === "order" ? Number(orderId) : null, product_id: scope === "product" ? Number(productId) : null, period_start: scope === "period" ? periodStart : null, period_end: scope === "period" ? periodEnd : null, allocation_strategy: strategy }),
    onSuccess: async () => { setShowForm(false); setDate(""); setAmount(""); setDescription(""); setError(null); await client.invalidateQueries({ queryKey: ["expenses", tenantId] }); await client.invalidateQueries({ queryKey: ["analytics", tenantId] }); },
    onError: (cause: unknown) => setError(cause instanceof ApiError ? cause.message : "ثبت هزینه ناموفق بود."),
  });
  const remove = useMutation({ mutationFn: (id: number) => apiRequest<void>(`/api/v1/expenses/${id}`, { method: "DELETE" }), onSuccess: async () => { await client.invalidateQueries({ queryKey: ["expenses", tenantId] }); }, onError: () => setError("حذف هزینه ناموفق بود.") });
  function submit(event: FormEvent<HTMLFormElement>) { event.preventDefault(); setError(null); create.mutate(); }

  return <section dir="rtl">
    <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-sm font-semibold text-teal-700">هزینه‌ها</p><h1 className="mt-1 text-2xl font-bold text-slate-900">مدیریت هزینه‌ها</h1><p className="mt-1 text-sm text-slate-500">هزینه‌ها را به سفارش، کالا یا دوره زمانی نسبت دهید.</p></div>{canWrite && <button type="button" onClick={() => setShowForm((value) => !value)} className="rounded-lg bg-teal-700 px-4 py-2.5 text-sm font-semibold text-white">{showForm ? "بستن فرم" : "ثبت هزینه"}</button>}</div>
    {showForm && <form className="mt-5 grid gap-3 rounded-xl border border-slate-200 bg-white p-5 sm:grid-cols-2" onSubmit={submit}>
      <Field label="تاریخ هزینه" type="date" value={date} onChange={setDate} required /><label className="block text-sm font-medium text-slate-700">نوع هزینه<select className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2.5" value={type} onChange={(event) => setType(event.target.value)}>{expenseTypes.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
      <Field label={`مبلغ (${currency ?? "واحد پول کسب‌وکار"})`} type="number" min="0.01" step="0.01" value={amount} onChange={setAmount} required /><Field label="شرح" value={description} onChange={setDescription} />
      <label className="block text-sm font-medium text-slate-700">نحوه تخصیص<select className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2.5" value={scope} onChange={(event) => setScope(event.target.value)}>{scopes.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
      {scope === "order" && <label className="block text-sm font-medium text-slate-700">سفارش<select className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2.5" value={orderId} onChange={(event) => setOrderId(event.target.value)} required><option value="">انتخاب سفارش</option>{orders.data?.data.map((order) => <option key={order.id} value={order.id}>{order.order_number} · {order.order_date}</option>)}</select></label>}
      {scope === "product" && <label className="block text-sm font-medium text-slate-700">کالا<select className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2.5" value={productId} onChange={(event) => setProductId(event.target.value)} required><option value="">انتخاب کالا</option>{products.data?.data.map((product) => <option key={product.id} value={product.id}>{product.name} · {product.sku}</option>)}</select></label>}
      {scope === "period" && <><Field label="شروع دوره" type="date" value={periodStart} onChange={setPeriodStart} required /><Field label="پایان دوره" type="date" value={periodEnd} onChange={setPeriodEnd} required /></>}
      <label className="block text-sm font-medium text-slate-700">روش تخصیص<select className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2.5" value={strategy} onChange={(event) => setStrategy(event.target.value)}>{strategies.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
      {error && <p role="alert" className="sm:col-span-2 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
      <div className="sm:col-span-2"><button type="submit" disabled={create.isPending || !currency || (scope === "order" && orders.isPending) || (scope === "product" && products.isPending)} className="rounded-lg bg-teal-700 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50">{create.isPending ? "در حال ثبت…" : "ثبت هزینه"}</button></div>
    </form>}
    {expenses.isPending ? <p role="status" className="mt-6 text-sm text-slate-500">در حال دریافت هزینه‌ها…</p> : expenses.isError ? <p role="alert" className="mt-6 text-sm text-red-700">دریافت هزینه‌ها ناموفق بود.</p> : <div className="mt-5 overflow-x-auto rounded-xl border border-slate-200 bg-white"><table className="w-full min-w-[760px] text-right text-sm"><thead className="bg-slate-50"><tr><th className="px-4 py-3">تاریخ</th><th className="px-4 py-3">نوع</th><th className="px-4 py-3">شرح</th><th className="px-4 py-3">مبلغ</th><th className="px-4 py-3">دامنه تخصیص</th><th className="px-4 py-3">روش</th><th className="px-4 py-3">عملیات</th></tr></thead><tbody className="divide-y divide-slate-100">{expenses.data.data.map((expense) => <tr key={expense.id}><td className="px-4 py-3">{expense.expense_date}</td><td className="px-4 py-3">{typeLabel(expense.type)}</td><td className="px-4 py-3">{expense.description ?? "—"}</td><td className="px-4 py-3 tabular-nums">{expense.amount} {expense.currency}</td><td className="px-4 py-3">{scopeLabel(expense.allocation_scope)}</td><td className="px-4 py-3">{strategyLabel(expense.allocation_strategy)}</td><td className="px-4 py-3">{canWrite && <button type="button" disabled={remove.isPending} onClick={() => { if (window.confirm("این هزینه به‌صورت نرم حذف شود؟")) remove.mutate(expense.id); }} className="text-xs text-red-700 hover:underline">حذف</button>}</td></tr>)}</tbody></table>{expenses.data.data.length === 0 && <p className="p-8 text-center text-sm text-slate-500">هنوز هزینه‌ای ثبت نشده است.</p>}</div>}
  </section>;
}
function Field({ label, value, onChange, required = false, type = "text", min, step }: { label: string; value: string; onChange: (value: string) => void; required?: boolean; type?: string; min?: string; step?: string }) { return <label className="block text-sm font-medium text-slate-700">{label}<input className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2.5" type={type} value={value} onChange={(event) => onChange(event.target.value)} required={required} min={min} step={step} /></label>; }
function typeLabel(value: string) { return expenseTypes.find((item) => item.value === value)?.label ?? value; }
function scopeLabel(value: string) { return scopes.find((item) => item.value === value)?.label ?? value; }
function strategyLabel(value: string | null) { return strategies.find((item) => item.value === value)?.label ?? "—"; }

