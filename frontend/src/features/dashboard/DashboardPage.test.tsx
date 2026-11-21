import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DashboardPage } from "./DashboardPage";

vi.mock("./TrendChart", () => ({ TrendChart: () => <div data-testid="trend-chart" /> }));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("financial dashboard", () => {
  it("shows server-calculated figures, unknown profit, warnings and trend chart", async () => {
    const summary = { currency: "IRT", revenue: "1000.00", known_cost_revenue: "800.00", unknown_cost_revenue: "200.00", cogs: null, gross_profit: null, net_profit: null, expenses: "100.00", margin_pct: null, sales_count: 3, units_sold: "5.000", returns_count: 1, returned_units: "1.000", refunds: "150.00", order_expenses: "50.00", unallocated_order_expenses: "0.00", period_expenses: "50.00", cancelled_order_expenses: "0.00", warnings: ["UNKNOWN_COST_REVENUE"], data_through: "2026-11-21T08:00:00+00:00", formula_version: "FV-2", calculation_id: 99 };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith("/api/v1/analytics/summary?")) return new Response(JSON.stringify({ data: summary }), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url.startsWith("/api/v1/analytics/products?")) return new Response(JSON.stringify({ data: { products: [{ product_id: 1, sku: "A1", name: "کالای نمونه", currency: "IRT", revenue: "1000.00", net_profit: null, gross_profit: null, margin_pct: null, units_sold: "5.000", returned_units: "1.000", warnings: ["UNKNOWN_COST_REVENUE"] }], warnings: ["UNKNOWN_COST_REVENUE"] } }), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url.startsWith("/api/v1/analytics/trends?")) return new Response(JSON.stringify({ data: { items: [{ period: "2026-11-21", revenue: "1000.00", refunds: "150.00", cogs: "0.00", expenses: "100.00", gross_profit: null }], currency: "IRT", data_through: summary.data_through, warnings: ["COST_UNKNOWN"] } }), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url.startsWith("/api/v1/analytics/expenses?")) return new Response(JSON.stringify({ data: { items: [{ type: "operational", scope: "period", amount: "100.00", currency: "IRT" }], total_in_period_profit: "100.00", product_scoped_excluded: "0.00", data_through: summary.data_through, warnings: [] } }), { status: 200, headers: { "Content-Type": "application/json" } });
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    client.setQueryData(["auth", "me"], { user: { id: 1, email: "owner@example.com", full_name: "Owner", is_platform_admin: false }, memberships: [], active_tenant: { id: 7, name: "فروشگاه", role: "owner", permissions: ["analytics:read"] } });
    render(<QueryClientProvider client={client}><DashboardPage /></QueryClientProvider>);
    expect(await screen.findByText("1000.00")).toBeTruthy();
    expect(screen.getAllByText("نامشخص").length).toBeGreaterThan(0);
    expect(screen.getByText(/بخشی از درآمد به دلیل بهای خرید نامشخص/)).toBeTruthy();
    expect(await screen.findByTestId("trend-chart")).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledTimes(4);
    expect(screen.getByRole("link", { name: /Excel/ }).getAttribute("href")).toContain("/api/v1/analytics/export.xlsx?");
    expect(screen.getByRole("button", { name: /PDF/ })).toBeTruthy();
  });
});





