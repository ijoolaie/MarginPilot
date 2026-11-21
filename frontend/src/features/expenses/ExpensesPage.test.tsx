import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ExpensesPage } from "./ExpensesPage";
import { clearCsrfToken } from "../../lib/api";

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  client.setQueryData(["auth", "me"], { user: { id: 1, email: "owner@example.com", full_name: "Owner", is_platform_admin: false }, memberships: [], active_tenant: { id: 7, name: "فروشگاه", role: "owner", permissions: ["expense:read", "expense:write"] } });
  client.setQueryData(["tenants"], { data: [{ id: 7, name: "فروشگاه", slug: "store", currency_code: "IRT", role: "owner", active: true }] });
  render(<QueryClientProvider client={client}><ExpensesPage /></QueryClientProvider>);
}

afterEach(() => { cleanup(); clearCsrfToken(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("expense entry", () => {
  it("creates a period expense with explicit allocation strategy and tenant currency", async () => {
    let created = false;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method ?? "GET").toUpperCase();
      if (url.startsWith("/api/v1/expenses?") && method === "GET") return new Response(JSON.stringify({ data: created ? [{ id: 3, expense_date: "2026-11-21", type: "operational", amount: "50000.00", currency: "IRT", description: "اجاره", allocation_scope: "period", order_id: null, product_id: null, period_start: "2026-11-01", period_end: "2026-11-30", allocation_strategy: "revenue_share" }] : [], pagination: { page: 1, pages: 1, total: created ? 1 : 0 } }), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/v1/expenses" && method === "POST") {
        expect(JSON.parse(String(init?.body))).toMatchObject({ expense_date: "2026-11-21", type: "operational", amount: "50000.00", currency: "IRT", allocation_scope: "period", period_start: "2026-11-01", period_end: "2026-11-30", allocation_strategy: "revenue_share" });
        created = true;
        return new Response(JSON.stringify({ data: { id: 3 } }), { status: 201, headers: { "Content-Type": "application/json" } });
      }
      throw new Error(`Unexpected request: ${method} ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "ثبت هزینه" }));
    fireEvent.change(screen.getByLabelText("تاریخ هزینه"), { target: { value: "2026-11-21" } });
    fireEvent.change(screen.getByLabelText(/مبلغ/), { target: { value: "50000.00" } });
    fireEvent.change(screen.getByLabelText("شرح"), { target: { value: "اجاره" } });
    fireEvent.change(screen.getByLabelText("شروع دوره"), { target: { value: "2026-11-01" } });
    fireEvent.change(screen.getByLabelText("پایان دوره"), { target: { value: "2026-11-30" } });
    fireEvent.click(screen.getByRole("button", { name: "ثبت هزینه" }));
    expect(await screen.findByText("اجاره")).toBeTruthy();
  });
});
