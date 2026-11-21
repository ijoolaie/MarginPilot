import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SalesOrdersPage } from "./SalesOrdersPage";
import { MemoryRouter } from "react-router";
import { clearCsrfToken } from "../../lib/api";

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  client.setQueryData(["auth", "me"], { user: { id: 1, email: "owner@example.com", full_name: "Owner", is_platform_admin: false }, memberships: [], active_tenant: { id: 7, name: "فروشگاه", role: "owner", permissions: ["sales:read", "sales:write"] } });
  client.setQueryData(["tenants"], { data: [{ id: 7, name: "فروشگاه", slug: "store", currency_code: "IRT", role: "owner", active: true }] });
  render(<QueryClientProvider client={client}><MemoryRouter><SalesOrdersPage /></MemoryRouter></QueryClientProvider>);
}

afterEach(() => { cleanup(); clearCsrfToken(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("sales order entry", () => {
  it("creates an order using server-side decimal allocation inputs", async () => {
    let created = false;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method ?? "GET").toUpperCase();
      if (url.startsWith("/api/v1/products?") && method === "GET") return new Response(JSON.stringify({ data: [{ id: 4, sku: "P-4", name: "کالای نمونه", unit: "piece", is_active: true }] }), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url.startsWith("/api/v1/sales/orders?") && method === "GET") return new Response(JSON.stringify({ data: created ? [{ id: 8, order_number: "SO-8", order_date: "2026-11-21", status: "pending", payment_status: "unpaid", shipping_status: "not_shipped", currency: "IRT" }] : [], pagination: { page: 1, pages: 1, total: created ? 1 : 0 } }), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/v1/sales/orders" && method === "POST") {
        expect(JSON.parse(String(init?.body))).toMatchObject({ order_number: "SO-8", currency: "IRT", items: [{ product_id: 4, quantity: "1.250", unit_price: "25000.50", line_discount: "0" }], order_discount: "0" });
        created = true;
        return new Response(JSON.stringify({ data: { id: 8, order_number: "SO-8" } }), { status: 201, headers: { "Content-Type": "application/json" } });
      }
      throw new Error(`Unexpected request: ${method} ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "ثبت سفارش فروش" }));
    await screen.findByRole("option", { name: /کالای نمونه/ });
    fireEvent.change(screen.getByLabelText("شماره سفارش"), { target: { value: "SO-8" } });
    fireEvent.change(screen.getByLabelText("تاریخ سفارش"), { target: { value: "2026-11-21" } });
    fireEvent.change(screen.getByLabelText("کالا"), { target: { value: "4" } });
    fireEvent.change(screen.getByLabelText("تعداد"), { target: { value: "1.250" } });
    fireEvent.change(screen.getByLabelText(/قیمت واحد/), { target: { value: "25000.50" } });
    fireEvent.click(screen.getByRole("button", { name: "ثبت سفارش" }));
    expect(await screen.findByText("SO-8")).toBeTruthy();
  });
});





