import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { api, ApiError } from "../../lib/api";
import { Link } from "react-router";
import type { AuthMe, TenantSummary } from "../auth/types";

type Product = { id: number; sku: string; name: string; unit: string; is_active: boolean };
type Order = { id: number; order_number: string; order_date: string; status: string; payment_status: string; shipping_status: string; currency: string; net_total?: string };
type OrderPage = { data: Order[]; pagination: { page: number; pages: number; total: number } };
type LineDraft = { product_id: string; quantity: string; unit_price: string; line_discount: string };

export function SalesOrdersPage() {
  const client = useQueryClient();
  const auth = client.getQueryData<AuthMe>(["auth", "me"]);
  const tenantId = auth?.active_tenant?.id;
  const canWrite = auth?.active_tenant?.permissions.includes("sales:write") ?? false;
  const tenantRows = client.getQueryData<{ data: TenantSummary[] }>(["tenants"]);
  const currency = tenantRows?.data.find((tenant) => tenant.id === tenantId)?.currency_code;
  const [showForm, setShowForm] = useState(false);
  const [orderNumber, setOrderNumber] = useState("");
  const [orderDate, setOrderDate] = useState("");
  const [customer, setCustomer] = useState("");
  const [channel, setChannel] = useState("");
  const [orderDiscount, setOrderDiscount] = useState("0");
  const [lines, setLines] = useState<LineDraft[]>([{ product_id: "", quantity: "1", unit_price: "", line_discount: "0" }]);
  const [error, setError] = useState<string | null>(null);
  const products = useQuery({ queryKey: ["products", tenantId, "sales-options"], queryFn: () => api.get<{ data: Product[] }>("/api/v1/products?page=1&page_size=100"), enabled: tenantId !== undefined });
  const orders = useQuery({ queryKey: ["sales-orders", tenantId], queryFn: () => api.get<OrderPage>("/api/v1/sales/orders?page=1&page_size=50"), enabled: tenantId !== undefined });
  const create = useMutation({
    mutationFn: () => api.post<{ data: Order }>("/api/v1/sales/orders", { order_number: orderNumber, order_date: orderDate, currency, items: lines.map((line) => ({ product_id: Number(line.product_id), quantity: line.quantity, unit_price: line.unit_price, line_discount: line.line_discount || "0" })), order_discount: orderDiscount, customer_name: customer || null, channel: channel || null }),
    onSuccess: async () => { setShowForm(false); setOrderNumber(""); setOrderDate(""); setCustomer(""); setChannel(""); setOrderDiscount("0"); setLines([{ product_id: "", quantity: "1", unit_price: "", line_discount: "0" }]); setError(null); await client.invalidateQueries({ queryKey: ["sales-orders", tenantId] }); },
    onError: (cause: unknown) => setError(cause instanceof ApiError ? cause.message : "ثبت سفارش ناموفق بود."),
  });
  function submit(event: FormEvent<HTMLFormElement>) { event.preventDefault(); setError(null); create.mutate(); }
  function updateLine(index: number, patch: Partial<LineDraft>) { setLines((current) => current.map((line, i) => i === index ? { ...line, ...patch } : line)); }

  return <section dir="rtl">
    <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-sm font-semibold text-teal-700">فروش</p><h1 className="mt-1 text-2xl font-bold text-slate-900">سفارش‌های فروش</h1><p className="mt-1 text-sm text-slate-500">ثبت فروش با snapshot بهای خرید و تخصیص تخفیف در سرور</p></div>{canWrite && <button type="button" onClick={() => setShowForm((value) => !value)} className="rounded-lg bg-teal-700 px-4 py-2.5 text-sm font-semibold text-white">{showForm ? "بستن فرم" : "ثبت سفارش فروش"}</button>}</div>
    {showForm && <form className="mt-5 space-y-4 rounded-xl border border-slate-200 bg-white p-5" onSubmit={submit}>
      <div className="grid gap-3 sm:grid-cols-2"><Field label="شماره سفارش" value={orderNumber} onChange={setOrderNumber} required /><Field label="تاریخ سفارش" type="date" value={orderDate} onChange={setOrderDate} required /><Field label="نام مشتری" value={customer} onChange={setCustomer} /><Field label="کانال فروش" value={channel} onChange={setChannel} /></div>
      <div className="flex items-center justify-between"><h2 className="font-semibold text-slate-800">اقلام سفارش</h2><button type="button" onClick={() => setLines((current) => [...current, { product_id: "", quantity: "1", unit_price: "", line_discount: "0" }])} className="text-sm font-semibold text-teal-700">افزودن ردیف</button></div>
      {lines.map((line, index) => <div key={index} className="grid gap-2 rounded-lg border border-slate-100 bg-slate-50 p-3 sm:grid-cols-4">
        <label className="block text-sm text-slate-700 sm:col-span-2">کالا<select className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-2 py-2" value={line.product_id} onChange={(event) => updateLine(index, { product_id: event.target.value })} required><option value="">انتخاب کالا</option>{products.data?.data.filter((product) => product.is_active).map((product) => <option key={product.id} value={product.id}>{product.name} · {product.sku} · {product.unit}</option>)}</select></label>
        <Field label="تعداد" type="number" min="0.001" step="0.001" value={line.quantity} onChange={(value) => updateLine(index, { quantity: value })} required /><Field label={`قیمت واحد${currency ? ` (${currency})` : ""}`} type="number" min="0" step="0.01" value={line.unit_price} onChange={(value) => updateLine(index, { unit_price: value })} required /><Field label="تخفیف ردیف" type="number" min="0" step="0.01" value={line.line_discount} onChange={(value) => updateLine(index, { line_discount: value })} />
        {lines.length > 1 && <button type="button" onClick={() => setLines((current) => current.filter((_, i) => i !== index))} className="text-right text-xs text-red-700 sm:col-span-4">حذف این ردیف</button>}
      </div>)}
      <div className="grid gap-3 sm:grid-cols-2"><Field label={`تخفیف کل سفارش${currency ? ` (${currency})` : ""}`} type="number" min="0" step="0.01" value={orderDiscount} onChange={setOrderDiscount} /></div>
      <p className="text-xs leading-6 text-slate-500">واحد پول سفارش از تنظیمات کسب‌وکار گرفته می‌شود. محاسبه و تخصیص تخفیف فقط در Backend انجام می‌شود.</p>
      {error && <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
      <button type="submit" disabled={create.isPending || !currency || products.isPending} className="rounded-lg bg-teal-700 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50">{create.isPending ? "در حال ثبت…" : "ثبت سفارش"}</button>
    </form>}
    {orders.isPending ? <p role="status" className="mt-6 text-sm text-slate-500">در حال دریافت سفارش‌ها…</p> : orders.isError ? <p role="alert" className="mt-6 text-sm text-red-700">دریافت سفارش‌ها ناموفق بود.</p> : <div className="mt-5 overflow-x-auto rounded-xl border border-slate-200 bg-white"><table className="w-full min-w-[720px] text-right text-sm"><thead className="bg-slate-50"><tr><th className="px-4 py-3">شماره سفارش</th><th className="px-4 py-3">تاریخ</th><th className="px-4 py-3">وضعیت سفارش</th><th className="px-4 py-3">پرداخت</th><th className="px-4 py-3">ارسال</th><th className="px-4 py-3">ارز</th><th className="px-4 py-3">جزئیات</th></tr></thead><tbody className="divide-y divide-slate-100">{orders.data.data.map((order) => <tr key={order.id}><td className="px-4 py-3 font-medium">{order.order_number}</td><td className="px-4 py-3">{order.order_date}</td><td className="px-4 py-3">{statusLabel(order.status)}</td><td className="px-4 py-3">{paymentLabel(order.payment_status)}</td><td className="px-4 py-3">{shippingLabel(order.shipping_status)}</td><td className="px-4 py-3">{order.currency}</td><td className="px-4 py-3"><Link className="font-semibold text-teal-700 hover:underline" to={`/sales/${order.id}`}>مشاهده</Link></td></tr>)}</tbody></table>{orders.data.data.length === 0 && <p className="p-8 text-center text-sm text-slate-500">هنوز سفارشی ثبت نشده است.</p>}</div>}
  </section>;
}
function Field({ label, value, onChange, required = false, type = "text", min, step }: { label: string; value: string; onChange: (value: string) => void; required?: boolean; type?: string; min?: string; step?: string }) { return <label className="block text-sm font-medium text-slate-700">{label}<input className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2.5" type={type} value={value} onChange={(event) => onChange(event.target.value)} required={required} min={min} step={step} /></label>; }
function statusLabel(value: string) { const labels: Record<string,string> = { pending: "در انتظار", confirmed: "تأییدشده", processing: "در حال پردازش", completed: "تکمیل‌شده", cancelled: "لغوشده" }; return labels[value] ?? value; }
function paymentLabel(value: string) { const labels: Record<string,string> = { unpaid: "پرداخت‌نشده", paid: "پرداخت‌شده", partially_refunded: "بازپرداخت جزئی", refunded: "بازپرداخت کامل" }; return labels[value] ?? value; }
function shippingLabel(value: string) { const labels: Record<string,string> = { not_shipped: "ارسال‌نشده", shipped: "ارسال‌شده", delivered: "تحویل‌شده", returned: "مرجوع‌شده" }; return labels[value] ?? value; }

