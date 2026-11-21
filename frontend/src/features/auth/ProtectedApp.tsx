import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { Link, Navigate, Outlet, useNavigate } from "react-router";
import { api, ApiError, clearCsrfToken } from "../../lib/api";
import { TenantPicker } from "../tenants/TenantPicker";
import type { AuthMe, TenantSummary } from "./types";

export function ProtectedApp() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [actionError, setActionError] = useState<string | null>(null);
  const auth = useQuery({
    queryKey: ["auth", "me"],
    queryFn: () => api.get<AuthMe>("/api/v1/auth/me"),
    retry: false,
    staleTime: 5 * 60 * 1000,
  });
  const tenants = useQuery({
    queryKey: ["tenants"],
    queryFn: () => api.get<{ data: TenantSummary[] }>("/api/v1/tenants"),
    enabled: Boolean(auth.data?.user && !auth.data.user.is_platform_admin),
    retry: false,
  });
  const logout = useMutation({
    mutationFn: () => api.post<void>("/api/v1/auth/logout"),
    onSuccess: () => {
      clearCsrfToken();
      queryClient.clear();
      navigate("/login", { replace: true });
    },
    onError: () => setActionError("خروج انجام نشد. اتصال سرور را بررسی کنید."),
  });
  const switchTenant = useMutation({
    mutationFn: (id: number) => api.post<void>(`/api/v1/tenants/${id}/activate`),
    onSuccess: async () => {
      setActionError(null);
      await queryClient.invalidateQueries();
    },
    onError: () => setActionError("تغییر کسب‌وکار انجام نشد. دوباره تلاش کنید."),
  });

  if (auth.isPending) return <FullPageMessage>در حال بررسی نشست کاربری…</FullPageMessage>;
  if (auth.error instanceof ApiError && auth.error.status === 401) return <Navigate to="/login" replace />;
  if (auth.isError) return <FullPageMessage><div><p>ارتباط با سرور برقرار نشد.</p><button className="mt-3 rounded-lg border border-slate-300 px-4 py-2 text-sm" type="button" onClick={() => void auth.refetch()}>تلاش دوباره</button></div></FullPageMessage>;
  if (auth.data.user.is_platform_admin) return <FullPageMessage>حساب مدیر پلتفرم به فضای کاری کسب‌وکار دسترسی مستقیم ندارد.</FullPageMessage>;
  if (!auth.data.active_tenant) return <FullPageMessage><TenantPicker /></FullPageMessage>;
  if (tenants.isPending) return <FullPageMessage>در حال دریافت اطلاعات کسب‌وکار…</FullPageMessage>;
  if (tenants.isError) return <FullPageMessage>دریافت اطلاعات فضای کاری ناموفق بود.</FullPageMessage>;

  return (
    <div className="min-h-screen bg-slate-50" dir="rtl">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-5 py-4">
          <div><p className="font-bold text-slate-900">MarginPilot</p><p className="text-xs text-slate-500">{auth.data.active_tenant.name}</p></div>
          <div className="flex items-center gap-3">
            {tenants.data.data.length > 1 && <select aria-label="انتخاب کسب‌وکار" className="max-w-48 rounded-lg border border-slate-300 bg-white px-2 py-2 text-sm" value={auth.data.active_tenant.id} onChange={(event) => switchTenant.mutate(Number(event.target.value))} disabled={switchTenant.isPending}>
              {tenants.data.data.map((tenant) => <option key={tenant.id} value={tenant.id}>{tenant.name}</option>)}
            </select>}
            <span className="hidden text-sm text-slate-600 sm:inline">{auth.data.user.full_name}</span>
            <button type="button" onClick={() => logout.mutate()} disabled={logout.isPending} className="rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-60">{logout.isPending ? "در حال خروج…" : "خروج"}</button>
          </div>
        </div>
        <nav className="mx-auto flex max-w-7xl gap-2 overflow-x-auto px-5 pb-3 text-sm" aria-label="ناوبری اصلی">
          <Link className="rounded-lg px-3 py-2 text-slate-700 hover:bg-slate-100" to="/">نمای کلی</Link>
          {auth.data.active_tenant.permissions.includes("product:read") && <Link className="rounded-lg px-3 py-2 text-slate-700 hover:bg-slate-100" to="/products">کالاها</Link>}
          {auth.data.active_tenant.permissions.includes("supplier:read") && <Link className="rounded-lg px-3 py-2 text-slate-700 hover:bg-slate-100" to="/suppliers">تأمین‌کنندگان</Link>}
          {auth.data.active_tenant.permissions.includes("import:execute") && <Link className="rounded-lg px-3 py-2 text-slate-700 hover:bg-slate-100" to="/imports">واردسازی</Link>}          {auth.data.active_tenant.permissions.includes("comparison:read") && <Link className="rounded-lg px-3 py-2 text-slate-700 hover:bg-slate-100" to="/comparison">مقایسه قیمت‌ها</Link>}          {auth.data.active_tenant.permissions.includes("sales:read") && <Link className="rounded-lg px-3 py-2 text-slate-700 hover:bg-slate-100" to="/sales">فروش</Link>}
          {auth.data.active_tenant.permissions.includes("expense:read") && <Link className="rounded-lg px-3 py-2 text-slate-700 hover:bg-slate-100" to="/expenses">هزینه‌ها</Link>}
        </nav>      </header>
      {actionError && <p role="alert" className="mx-auto mt-4 max-w-7xl px-5 text-sm text-red-700">{actionError}</p>}
      <main className="mx-auto max-w-7xl px-5 py-8"><Outlet /></main>
    </div>
  );
}

function FullPageMessage({ children }: { children: ReactNode }) {
  return <main className="flex min-h-screen items-center justify-center bg-slate-50 p-5 text-center text-slate-600" dir="rtl">{children}</main>;
}






