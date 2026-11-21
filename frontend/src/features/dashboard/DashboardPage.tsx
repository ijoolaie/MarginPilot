import { lazy, Suspense, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../lib/api";
import type { AuthMe } from "../auth/types";
import type { EChartsOption } from "echarts";

const TrendChart = lazy(() => import("./TrendChart").then((module) => ({ default: module.TrendChart })));

type Summary = { currency: string; revenue: string; known_cost_revenue: string; unknown_cost_revenue: string; cogs: string | null; gross_profit: string | null; net_profit: string | null; expenses: string; margin_pct: string | null; sales_count: number; units_sold: string; returns_count: number; returned_units: string; refunds: string; order_expenses: string; unallocated_order_expenses: string; period_expenses: string; cancelled_order_expenses: string; warnings: string[]; data_through: string; formula_version: string; calculation_id: number };
type ProductMetric = { product_id: number; sku: string; name: string; currency: string; revenue: string; net_profit: string | null; gross_profit: string | null; margin_pct: string | null; units_sold: string; returned_units: string; warnings: string[] };
type TrendItem = { period: string; revenue: string; refunds: string; cogs: string; expenses: string; gross_profit: string | null };
type ExpenseItem = { type: string; scope: string; amount: string; currency: string };
const warningLabels: Record<string,string> = { UNKNOWN_COST_SOURCE: "بهای خرید بعضی اقلام مشخص نیست؛ سود آن‌ها قطعی نیست.", UNKNOWN_COST_REVENUE: "بخشی از درآمد به دلیل بهای خرید نامشخص، سود قطعی ندارد.", UNALLOCATED_ORDER_COSTS: "بخشی از هزینه سفارش قابل تخصیص به اقلام نبود.", UNALLOCATED_PERIOD_COSTS: "هزینه دوره به دلیل نبود مبنای تخصیص، تخصیص‌نیافته باقی مانده است.", CANCELLED_ORDER_COSTS_UNALLOCATED: "هزینه سفارش‌های لغوشده به‌صورت تخصیص‌نیافته گزارش شده است.", CANCELLED_ORDER_COSTS_UNATTRIBUTED: "هزینه سفارش لغوشده به محصول یا فروش نسبت داده نشده است.", COST_UNKNOWN: "بهای تمام‌شده در بخشی از بازه نامشخص است." };
const expenseLabels: Record<string,string> = { shipping: "حمل‌ونقل", packaging: "بسته‌بندی", advertising: "تبلیغات", payment_fee: "کارمزد پرداخت", operational: "عملیاتی", other: "سایر" };
function localDate(date: Date) { return `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,"0")}-${String(date.getDate()).padStart(2,"0")}`; }

export function DashboardPage() {
  const client = useQueryClient();
  const auth = client.getQueryData<AuthMe>(["auth", "me"]);
  const tenantId = auth?.active_tenant?.id;
  const canRead = auth?.active_tenant?.permissions.includes("analytics:read") ?? false;
  const [dateFrom, setDateFrom] = useState(() => { const start = new Date(); start.setDate(start.getDate() - 29); return localDate(start); });
  const [dateTo, setDateTo] = useState(() => localDate(new Date()));
  const [groupBy, setGroupBy] = useState<"day" | "month">("day");
  const validRange = dateFrom !== "" && dateTo !== "" && dateFrom <= dateTo && (new Date(`${dateTo}T00:00:00`).getTime() - new Date(`${dateFrom}T00:00:00`).getTime()) / 86400000 <= 365;
  const params = `date_from=${dateFrom}&date_to=${dateTo}`;
  const summary = useQuery({ queryKey: ["analytics", tenantId, "summary", dateFrom, dateTo], queryFn: () => api.get<{ data: Summary }>(`/api/v1/analytics/summary?${params}`), enabled: canRead && validRange });
  const products = useQuery({ queryKey: ["analytics", tenantId, "products", dateFrom, dateTo], queryFn: () => api.get<{ data: { products: ProductMetric[]; warnings: string[] } }>(`/api/v1/analytics/products?${params}`), enabled: canRead && validRange });
  const trends = useQuery({ queryKey: ["analytics", tenantId, "trends", dateFrom, dateTo, groupBy], queryFn: () => api.get<{ data: { items: TrendItem[]; currency: string; data_through: string; warnings: string[] } }>(`/api/v1/analytics/trends?${params}&group_by=${groupBy}`), enabled: canRead && validRange });
  const expenses = useQuery({ queryKey: ["analytics", tenantId, "expenses", dateFrom, dateTo], queryFn: () => api.get<{ data: { items: ExpenseItem[]; total_in_period_profit: string; product_scoped_excluded: string; data_through: string; warnings: string[] } }>(`/api/v1/analytics/expenses?${params}`), enabled: canRead && validRange });
  const chartOption = useMemo<EChartsOption>(() => ({
    tooltip: { trigger: "axis" }, legend: { data: ["درآمد", "سود ناخالص", "هزینه‌ها", "بازپرداخت"] },
    grid: { left: 18, right: 18, bottom: 28, top: 42, containLabel: true },
    xAxis: { type: "category", data: trends.data?.data.items.map((item) => item.period) ?? [], axisLabel: { hideOverlap: true } },
    yAxis: { type: "value", axisLabel: { formatter: (value: number) => new Intl.NumberFormat("fa-IR", { notation: "compact" }).format(value) } },
    series: [
      { name: "درآمد", type: "line", smooth: true, data: trends.data?.data.items.map((item) => Number(item.revenue)) ?? [] },
      { name: "سود ناخالص", type: "line", smooth: true, connectNulls: false, data: trends.data?.data.items.map((item) => item.gross_profit === null ? null : Number(item.gross_profit)) ?? [] },
      { name: "هزینه‌ها", type: "line", data: trends.data?.data.items.map((item) => Number(item.expenses)) ?? [] },
      { name: "بازپرداخت", type: "line", data: trends.data?.data.items.map((item) => Number(item.refunds)) ?? [] },
    ],
  }), [trends.data]);

  if (!canRead) return <p role="alert" className="text-sm text-red-700" dir="rtl">مجوز مشاهده گزارش‌های تحلیلی برای این حساب فعال نیست.</p>;
  const data = summary.data?.data;
  const warnings = [...new Set([...(data?.warnings ?? []), ...(products.data?.data.warnings ?? []), ...(trends.data?.data.warnings ?? []), ...(expenses.data?.data.warnings ?? [])])];
  return <section dir="rtl">
    <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-sm font-semibold text-teal-700">تحلیل مالی</p><h1 className="mt-1 text-2xl font-bold text-slate-900">داشبورد سود و عملکرد</h1><p className="mt-1 text-sm text-slate-500">تمام ارقام از موتور محاسباتی سرور دریافت می‌شوند؛ فرمول {data?.formula_version ?? "FV-2"}</p></div><div className="flex gap-2 print:hidden"><a aria-disabled={!validRange} className="rounded-lg bg-teal-700 px-3 py-2 text-sm font-semibold text-white aria-disabled:pointer-events-none aria-disabled:opacity-50" href={validRange ? `/api/v1/analytics/export.xlsx?${params}&group_by=${groupBy}` : undefined}>دریافت Excel</a><button type="button" disabled={!validRange || !data} onClick={() => window.print()} className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 disabled:opacity-50">چاپ / PDF</button></div></div>
    <div className="mt-5 flex flex-wrap items-end gap-3 rounded-xl border border-slate-200 bg-white p-4"><label className="block text-sm text-slate-700">از تاریخ<input className="mt-1 block rounded-lg border border-slate-300 px-3 py-2" type="date" value={dateFrom} max={dateTo || undefined} onChange={(event) => setDateFrom(event.target.value)} /></label><label className="block text-sm text-slate-700">تا تاریخ<input className="mt-1 block rounded-lg border border-slate-300 px-3 py-2" type="date" value={dateTo} min={dateFrom || undefined} onChange={(event) => setDateTo(event.target.value)} /></label><label className="block text-sm text-slate-700">دوره نمودار<select className="mt-1 block rounded-lg border border-slate-300 px-3 py-2" value={groupBy} onChange={(event) => setGroupBy(event.target.value as "day" | "month")}><option value="day">روزانه</option><option value="month">ماهانه</option></select></label><span className="text-xs text-slate-500">حداکثر بازه: ۳۶۵ روز</span></div>
    {!validRange && <p role="alert" className="mt-3 text-sm text-red-700">بازه تاریخ معتبر نیست یا بیش از ۳۶۵ روز است.</p>}
    {summary.isPending && validRange ? <p role="status" className="mt-5 text-sm text-slate-500">در حال محاسبه گزارش‌ها…</p> : summary.isError ? <p role="alert" className="mt-5 text-sm text-red-700">دریافت خلاصه مالی ناموفق بود.</p> : data && <>
      <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{[
        ["درآمد شناسایی‌شده", data.revenue, data.currency], ["سود ناخالص", data.gross_profit, data.currency], ["سود عملیاتی خالص", data.net_profit, data.currency], ["حاشیه سود", data.margin_pct === null ? null : `${data.margin_pct}%`, ""],
        ["بهای تمام‌شده", data.cogs, data.currency], ["هزینه‌های دوره", data.expenses, data.currency], ["بازپرداخت‌ها", data.refunds, data.currency], ["تعداد سفارش", String(data.sales_count), ""],
      ].map(([label,value,unit]) => <div key={String(label)} className="rounded-xl border border-slate-200 bg-white p-4"><p className="text-xs text-slate-500">{label}</p><p className="mt-2 text-xl font-bold tabular-nums text-slate-900">{value === null ? "نامشخص" : value}</p><p className="mt-1 text-xs text-slate-500">{unit}</p></div>)}</div>
      <div className="mt-5 rounded-xl border border-slate-200 bg-white p-5"><div className="flex flex-wrap justify-between gap-2"><h2 className="font-semibold text-slate-900">روند عملکرد</h2><span className="text-xs text-slate-500">{groupBy === "day" ? "روزانه" : "ماهانه"} · {data.currency}</span></div>{trends.isPending ? <p className="mt-4 text-sm text-slate-500">در حال دریافت روند…</p> : trends.isError ? <p className="mt-4 text-sm text-red-700">دریافت روند ناموفق بود.</p> : <Suspense fallback={<p className="py-12 text-center text-sm text-slate-500">در حال بارگذاری نمودار…</p>}><TrendChart option={chartOption} /></Suspense>}</div>
      <div className="mt-5 overflow-x-auto rounded-xl border border-slate-200 bg-white"><div className="p-5"><h2 className="font-semibold text-slate-900">سودآوری کالاها</h2><p className="mt-1 text-xs text-slate-500">سود نامشخص عمداً صفر نمایش داده نمی‌شود.</p></div>{products.isPending ? <p className="px-5 pb-5 text-sm text-slate-500">در حال دریافت کالاها…</p> : products.isError ? <p className="px-5 pb-5 text-sm text-red-700">دریافت سود کالاها ناموفق بود.</p> : <table className="w-full min-w-[760px] text-right text-sm"><thead className="bg-slate-50"><tr><th className="px-4 py-3">کالا</th><th className="px-4 py-3">درآمد</th><th className="px-4 py-3">سود خالص</th><th className="px-4 py-3">حاشیه سود</th><th className="px-4 py-3">فروش</th><th className="px-4 py-3">مرجوعی</th></tr></thead><tbody className="divide-y divide-slate-100">{products.data.data.products.map((product) => <tr key={product.product_id}><td className="px-4 py-3"><span className="font-medium">{product.name}</span><span className="block text-xs text-slate-500">{product.sku}</span></td><td className="px-4 py-3 tabular-nums">{product.revenue} {product.currency}</td><td className="px-4 py-3 tabular-nums">{product.net_profit === null ? "نامشخص" : `${product.net_profit} ${product.currency}`}</td><td className="px-4 py-3">{product.margin_pct === null ? "نامشخص" : `${product.margin_pct}%`}</td><td className="px-4 py-3">{product.units_sold}</td><td className="px-4 py-3">{product.returned_units}</td></tr>)}</tbody></table>}</div>
      <div className="mt-5 rounded-xl border border-slate-200 bg-white p-5"><h2 className="font-semibold text-slate-900">ترکیب هزینه‌ها</h2>{expenses.isPending ? <p className="mt-3 text-sm text-slate-500">در حال دریافت هزینه‌ها…</p> : expenses.isError ? <p className="mt-3 text-sm text-red-700">دریافت هزینه‌ها ناموفق بود.</p> : <><div className="mt-3 space-y-2">{expenses.data.data.items.map((item,index) => <div key={`${item.type}-${item.scope}-${index}`} className="flex justify-between gap-3 border-b border-slate-100 pb-2 text-sm"><span>{expenseLabels[item.type] ?? item.type} · {item.scope}</span><span className="tabular-nums">{item.amount} {item.currency}</span></div>)}</div><p className="mt-3 text-sm font-semibold">هزینه مؤثر بر سود دوره: {expenses.data.data.total_in_period_profit} {data.currency}</p></>}</div>
      {warnings.length > 0 && <div className="mt-5 rounded-xl border border-amber-200 bg-amber-50 p-5"><h2 className="font-semibold text-amber-900">هشدارهای گزارش</h2><ul className="mt-2 list-disc space-y-1 pr-5 text-sm text-amber-800">{warnings.map((warning) => <li key={warning}>{warningLabels[warning] ?? warning}</li>)}</ul></div>}
      <p className="mt-4 text-xs text-slate-500">آخرین داده: {new Date(data.data_through).toLocaleString("fa-IR")} · شناسه محاسبه: {data.calculation_id}</p>
    </>}
  </section>;
}









