import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router";
import { SalesOrderDetailPage } from "./SalesOrderDetailPage";
import { clearCsrfToken } from "../../lib/api";

const order = { id: 1, order_number: "SO-1", order_date: "2026-11-21", status: "completed", payment_status: "paid", shipping_status: "delivered", currency: "IRT", order_discount: "0.00", customer_name: "مشتری", gross_total: "100.00", net_total: "100.00", items: [{ id: 11, product_id: 4, sku: "P-4", name: "کالای نمونه", quantity: "1.000", unit_price: "100.00", line_discount: "0.00", order_discount_share: "0.00", unit_cost: "50.00", cost_source: "product_snapshot", returned_quantity: "0.000" }] };
function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  client.setQueryData(["auth", "me"], { user: { id: 1, email: "owner@example.com", full_name: "Owner", is_platform_admin: false }, memberships: [], active_tenant: { id: 7, name: "فروشگاه", role: "owner", permissions: ["sales:read", "sales:write", "pricing:read"] } });
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/sales/1"]}><Routes><Route path="/sales/:orderId" element={<SalesOrderDetailPage />} /></Routes></MemoryRouter></QueryClientProvider>);
}

afterEach(() => { cleanup(); clearCsrfToken(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("sales order detail", () => {
  it("records the actual physical-return refund without capping it at line revenue", async () => {
    let returned = false;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method ?? "GET").toUpperCase();
      if (url === "/api/v1/sales/orders/1") return new Response(JSON.stringify({ data: returned ? { ...order, items: [{ ...order.items[0], returned_quantity: "1.000" }] } : order }), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/v1/sales/orders/1/returns" && method === "GET") return new Response(JSON.stringify({ data: returned ? [{ id: 3, return_number: "RET-3", return_date: "2026-11-21", refund_metadata: { refund_total: "150.00" } }] : [] }), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/v1/sales/orders/1/refunds" && method === "GET") return new Response(JSON.stringify({ data: [] }), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/v1/sales/orders/1/profit") return new Response(JSON.stringify({ data: { currency: "IRT", revenue: "-50.00", cogs: "0.00", gross_profit: "-50.00", net_operating_profit: "-50.00", margin_pct: null, expenses: "0.00", formula_version: "FV-2", calculation_id: 7, warnings: [] } }), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/v1/sales/orders/1/returns" && method === "POST") {
        expect(new Headers(init?.headers).get("Idempotency-Key")).toBeTruthy();
        expect(JSON.parse(String(init?.body))).toMatchObject({ items: [{ sale_item_id: 11, quantity: "1", refund_amount: "150.00" }] });
        returned = true;
        return new Response(JSON.stringify({ data: { id: 3 } }), { status: 201, headers: { "Content-Type": "application/json" } });
      }
      throw new Error(`Unexpected request: ${method} ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderPage();
    expect(await screen.findByText("کالای نمونه")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("قلم سفارش"), { target: { value: "11" } });
    fireEvent.change(screen.getByLabelText("تعداد مرجوعی"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText(/مبلغ بازپرداخت/), { target: { value: "150.00" } });
    fireEvent.click(screen.getByRole("button", { name: "ثبت مرجوعی" }));
    expect(await screen.findByText("RET-3")).toBeTruthy();
  });
});

