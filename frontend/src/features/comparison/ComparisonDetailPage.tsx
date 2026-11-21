import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router";
import { ApiError, api, apiRequest } from "../../lib/api";
import type { AuthMe } from "../auth/types";

type Price = { id: number; sku: string | null; raw_name: string; unit_price: string; unit: string; currency: string };
type PriceList = { id: number; title: string; items: Price[] };
type Match = { id: number; base_price_id: number | null; target_price_id: number | null; base_raw_name: string | null; target_raw_name: string | null; base_price: Price | null; target_price: Price | null; match_type: string; status: string; suggested_product_id: number | null; confirmed_product_id: number | null; price_delta: string | null; price_delta_pct: string | null };
type Product = { id: number; sku: string; name: string; unit: string; is_active: boolean };
type RunDetail = { id: number; status: string; summary: Record<string, number>; base_list: { id: number; title: string; received_at: string; supplier: { name: string } }; target_list: { id: number; title: string; received_at: string; supplier: { name: string } }; matches: Match[] };
type DecisionState = { decision: "" | "confirm" | "reject"; product_id: string; peer_price_id: string };

export function ComparisonDetailPage() {
  const { runId } = useParams();
  const id = Number(runId);
  const client = useQueryClient();
  const auth = client.getQueryData<AuthMe>(["auth", "me"]);
  const tenantId = auth?.active_tenant?.id;
  const canWrite = auth?.active_tenant?.permissions.includes("comparison:write") ?? false;
  const [decisions, setDecisions] = useState<Record<number, DecisionState>>({});
  const [error, setError] = useState<string | null>(null);
  const query = useQuery({
    queryKey: ["comparison", tenantId, id],
    enabled: tenantId !== undefined && Number.isInteger(id) && id > 0,
    queryFn: async () => {
      const first = await api.get<{ data: RunDetail; meta: { page: number; page_size: number; total_items: number } }>(`/api/v1/comparison/runs/${id}?page=1&page_size=200`);
      const matches = [...first.data.matches];
      const pages = Math.ceil(first.meta.total_items / first.meta.page_size);
      for (let page = 2; page <= pages; page += 1) {
        const next = await api.get<{ data: RunDetail; meta: { total_items: number } }>(`/api/v1/comparison/runs/${id}?page=${page}&page_size=200`);
        matches.push(...next.data.matches);
      }
      const [baseList, targetList, products] = await Promise.all([
        api.get<{ data: PriceList }>(`/api/v1/price-lists/${first.data.base_list.id}`),
        api.get<{ data: PriceList }>(`/api/v1/price-lists/${first.data.target_list.id}`),
        api.get<{ data: Product[] }>("/api/v1/products?page=1&page_size=100"),
      ]);
      return { ...first.data, matches, baseItems: baseList.data.items, targetItems: targetList.data.items, products: products.data };
    },
  });
  const confirm = useMutation({
    mutationFn: (payload: { decisions: Array<{ match_id: number; decision: "confirm" | "reject"; product_id?: number; peer_price_id?: number }> }) => apiRequest<{ data: { status: string; confirmed: number; rejected: number; pending: number } }>(`/api/v1/comparison/runs/${id}/confirm-matches`, { method: "POST", body: JSON.stringify(payload) }),
    onSuccess: async () => { setError(null); setDecisions({}); await client.invalidateQueries({ queryKey: ["comparison", tenantId, id] }); },
    onError: (cause: unknown) => setError(cause instanceof ApiError ? cause.message : "ثبت تصمیم‌ها ناموفق بود."),
  });
  const data = query.data;
  const pending = useMemo(() => data?.matches.filter((match) => match.status === "pending") ?? [], [data]);
  const peerUseCounts = useMemo(() => { const counts = new Map<number, number>(); for (const decision of Object.values(decisions)) { if (decision.decision === "confirm" && decision.peer_price_id) { const peerId = Number(decision.peer_price_id); counts.set(peerId, (counts.get(peerId) ?? 0) + 1); } } return counts; }, [decisions]);
  const selectedPeerIds = useMemo(() => new Set(peerUseCounts.keys()), [peerUseCounts]);

  function updateDecision(matchId: number, patch: Partial<DecisionState>) {
    setDecisions((current) => { const suggested = data?.matches.find((match) => match.id === matchId)?.suggested_product_id; const previous = current[matchId] ?? { decision: "", product_id: String(suggested ?? ""), peer_price_id: "" }; return { ...current, [matchId]: { ...previous, ...patch } }; });
  }
  function submitDecisions() {
    if (!data) return;
    const selected = pending.filter((match) => Boolean(decisions[match.id]?.decision));
    if (!selected.length) { setError("برای ثبت، دست‌کم یک تصمیم انتخاب کنید."); return; }
    if ([...peerUseCounts.values()].some((count) => count > 1)) { setError("هر قیمت همتا فقط می‌تواند به یک ردیف متصل شود."); return; }
    for (const match of selected) {
      const state = decisions[match.id];
      if (state.decision !== "confirm") continue;
      const needsPeer = match.base_price_id === null || match.target_price_id === null;
      if (!state.product_id || (needsPeer && !state.peer_price_id)) { setError("برای تأیید، کالا و در صورت نیاز قیمت همتا را انتخاب کنید."); return; }
      const ownPrice = match.base_price ?? match.target_price;
      const peerPrice = state.peer_price_id ? (match.base_price_id !== null ? data.targetItems.find((item) => item.id === Number(state.peer_price_id)) : data.baseItems.find((item) => item.id === Number(state.peer_price_id))) : null;
      const product = data.products.find((item) => item.id === Number(state.product_id));
      if (!product || !ownPrice || product.unit !== ownPrice.unit || (peerPrice && peerPrice.unit !== ownPrice.unit) || (peerPrice && product.unit !== peerPrice.unit)) { setError("واحد کالا و قیمت‌های انتخاب‌شده باید یکسان باشد."); return; }
    }
    const payload: Array<{ match_id: number; decision: "confirm" | "reject"; product_id?: number; peer_price_id?: number }> = [];
    for (const match of selected) {
      const state = decisions[match.id];
      const ownPriceId = match.base_price_id ?? match.target_price_id;
      if ((match.base_price_id === null || match.target_price_id === null) && ownPriceId !== null && selectedPeerIds.has(ownPriceId)) continue;
      if (state.decision === "reject") payload.push({ match_id: match.id, decision: "reject" });
      else payload.push({ match_id: match.id, decision: "confirm", product_id: Number(state.product_id), ...(state.peer_price_id ? { peer_price_id: Number(state.peer_price_id) } : {}) });
    }
    if (!payload.length) { setError("دو ردیف انتخاب‌شده نمی‌توانند هم‌زمان همتای یکدیگر باشند."); return; }
    setError(null);
    confirm.mutate({ decisions: payload });
  }
  if (query.isPending) return <p role="status" className="text-sm text-slate-500" dir="rtl">در حال دریافت جزئیات مقایسه…</p>;
  if (query.isError || !data) return <p role="alert" className="text-sm text-red-700" dir="rtl">دریافت جزئیات مقایسه ناموفق بود.</p>;
  const baseOnly = pending.filter((match) => match.base_price_id !== null && match.target_price_id === null);
  const targetOnly = pending.filter((match) => match.base_price_id === null && match.target_price_id !== null);

  return <section dir="rtl">
    <Link className="text-sm font-medium text-teal-700 hover:underline" to="/comparison">بازگشت به مقایسه‌ها</Link>
    <h1 className="mt-2 text-2xl font-bold text-slate-900">مقایسه شماره {data.id}</h1>
    <p className="mt-2 text-sm text-slate-500">{data.base_list.supplier.name} · {data.base_list.title} ({data.base_list.received_at}) در برابر {data.target_list.supplier.name} · {data.target_list.title} ({data.target_list.received_at})</p>
    <div className="mt-5 grid gap-3 sm:grid-cols-4">{[["کل ردیف‌ها",data.summary.total_matches],["تطبیق‌شده",data.summary.matched],["افزایش قیمت",data.summary.increased],["نیازمند بررسی",data.summary.uncertain]].map(([label,value]) => <div key={String(label)} className="rounded-xl border border-slate-200 bg-white p-4"><p className="text-xs text-slate-500">{label}</p><p className="mt-1 text-xl font-bold tabular-nums text-slate-900">{value}</p></div>)}</div>
    <div className="mt-5 overflow-x-auto rounded-xl border border-slate-200 bg-white"><table className="w-full min-w-[850px] text-right text-sm"><thead className="bg-slate-50"><tr><th className="px-3 py-3">کالای مبنا</th><th className="px-3 py-3">قیمت مبنا</th><th className="px-3 py-3">کالای هدف</th><th className="px-3 py-3">قیمت هدف</th><th className="px-3 py-3">اختلاف</th><th className="px-3 py-3">وضعیت</th></tr></thead><tbody className="divide-y divide-slate-100">{data.matches.map((match) => <tr key={match.id}><td className="px-3 py-3">{match.base_raw_name ?? "—"}</td><td className="px-3 py-3 tabular-nums">{match.base_price ? `${match.base_price.unit_price} ${match.base_price.currency}` : "—"}</td><td className="px-3 py-3">{match.target_raw_name ?? "—"}</td><td className="px-3 py-3 tabular-nums">{match.target_price ? `${match.target_price.unit_price} ${match.target_price.currency}` : "—"}</td><td className="px-3 py-3 tabular-nums">{match.price_delta ?? "—"}{match.price_delta_pct ? ` (${match.price_delta_pct}%)` : ""}</td><td className="px-3 py-3">{match.status === "pending" ? "نیازمند بررسی" : match.status === "confirmed" ? "تأییدشده" : "ردشده"}</td></tr>)}</tbody></table></div>
    {canWrite && pending.length > 0 && <div className="mt-6 rounded-xl border border-slate-200 bg-white p-5"><h2 className="font-semibold text-slate-900">بررسی تطبیق‌های مبهم ({pending.length})</h2><p className="mt-1 text-sm text-slate-500">تأیید، کالا را به هر دو قیمت پیوند می‌دهد؛ رد کردن فقط تطبیق پیشنهادی را رد می‌کند. قیمت‌ها و واحدها پیش از تأیید بررسی شوند.</p>
      <div className="mt-4 space-y-4">{pending.map((match) => {
        const state = decisions[match.id] ?? { decision: "", product_id: String(match.suggested_product_id ?? ""), peer_price_id: "" };
        const needsPeer = match.base_price_id === null || match.target_price_id === null;
        const peerCandidates = match.base_price_id !== null ? targetOnly.filter((item) => item.target_price_id !== null) : baseOnly.filter((item) => item.base_price_id !== null);
        const peerPrice = state.peer_price_id ? (match.base_price_id !== null ? data.targetItems.find((item) => item.id === Number(state.peer_price_id)) : data.baseItems.find((item) => item.id === Number(state.peer_price_id))) : null;
        const ownPrice = match.base_price ?? match.target_price;
        const peerMismatch = Boolean(peerPrice && ownPrice && peerPrice.unit !== ownPrice.unit);
        const product = data.products.find((item) => item.id === Number(state.product_id));
        const productMismatch = Boolean(product && ownPrice && product.unit !== ownPrice.unit) || Boolean(product && peerPrice && product.unit !== peerPrice.unit);
        const peerAlreadyUsed = peerPrice ? (peerUseCounts.get(peerPrice.id) ?? 0) > 1 : false;
        return <div key={match.id} className="rounded-lg border border-slate-200 p-4"><div className="flex flex-wrap justify-between gap-2"><p className="font-medium text-slate-800">{match.base_raw_name ?? match.target_raw_name ?? "ردیف مبهم"}</p><span className="text-xs text-slate-500">{match.match_type === "uncertain" ? "تطبیق نامطمئن" : "تطبیق ناقص"}</span></div>
          <div className="mt-3 grid gap-3 sm:grid-cols-3">
            <label className="block text-sm text-slate-700">تصمیم<select className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-2" value={state.decision} onChange={(event) => updateDecision(match.id, { decision: event.target.value as DecisionState["decision"] })}><option value="">انتخاب کنید</option><option value="confirm">تأیید</option><option value="reject">رد</option></select></label>
            {state.decision === "confirm" && <label className="block text-sm text-slate-700">کالای متناظر<select className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-2" value={state.product_id} onChange={(event) => updateDecision(match.id, { product_id: event.target.value })}><option value="">انتخاب کالا</option>{data.products.filter((item) => item.is_active).map((item) => <option key={item.id} value={item.id}>{item.name} · {item.sku} · {item.unit}</option>)}</select></label>}
            {state.decision === "confirm" && needsPeer && <label className="block text-sm text-slate-700">قیمت همتای لیست دیگر<select className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-2" value={state.peer_price_id} onChange={(event) => updateDecision(match.id, { peer_price_id: event.target.value })}><option value="">انتخاب ردیف متناظر</option>{peerCandidates.map((candidate) => { const price = match.base_price_id !== null ? candidate.target_price : candidate.base_price; return price ? <option key={price.id} value={price.id} disabled={(peerUseCounts.get(price.id) ?? 0) > 0 && state.peer_price_id !== String(price.id)}>{price.raw_name} · {price.unit_price} · {price.unit}</option> : null; })}</select></label>}
          </div>
          {state.decision === "confirm" && (needsPeer && !state.peer_price_id || !state.product_id) && <p className="mt-2 text-xs text-amber-700">برای تأیید، کالا و در صورت نیاز قیمت همتا را انتخاب کنید.</p>}
          {state.decision === "confirm" && (peerMismatch || productMismatch || peerAlreadyUsed) && <p role="alert" className="mt-2 text-xs text-red-700">واحد قیمت‌ها یا واحد کالای انتخاب‌شده سازگار نیست، یا قیمت همتا قبلاً انتخاب شده است.</p>}
        </div>;
      })}</div>
      {error && <p role="alert" className="mt-4 text-sm text-red-700">{error}</p>}
      <button type="button" onClick={submitDecisions} disabled={confirm.isPending} className="mt-4 rounded-lg bg-teal-700 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50">{confirm.isPending ? "در حال ثبت تصمیم‌ها…" : "ثبت تصمیم‌های انتخاب‌شده"}</button>
    </div>}
  </section>;
}





