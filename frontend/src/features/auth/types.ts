export type ActiveTenant = { id: number; name: string; role: string; permissions: string[] };
export type AuthMe = {
  user: { id: number; email: string; full_name: string; is_platform_admin: boolean };
  memberships: Array<{ tenant_id: number; tenant_name: string; role: string }>;
  active_tenant: ActiveTenant | null;
};
export type TenantSummary = { id: number; name: string; slug: string; currency_code: "IRT" | "IRR"; role: string; active: boolean };
