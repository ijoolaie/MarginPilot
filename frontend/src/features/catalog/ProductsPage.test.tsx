import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ProductsPage } from "./ProductsPage";
import { clearCsrfToken } from "../../lib/api";

const product = { id: 1, sku: "SKU-1", name: "کالای نمونه", unit: "piece", sale_price: "120000", purchase_cost: "80000", is_active: true };
function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  client.setQueryData(["auth", "me"], { user: { id: 1, email: "owner@example.com", full_name: "Owner", is_platform_admin: false }, memberships: [], active_tenant: { id: 7, name: "فروشگاه", role: "owner", permissions: ["product:read", "product:write"] } });
  render(<QueryClientProvider client={client}><ProductsPage /></QueryClientProvider>);
}

afterEach(() => { cleanup(); clearCsrfToken(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("product catalog", () => {
  it("loads tenant-scoped products and creates a product with decimal strings", async () => {
    let created: typeof product | null = null;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method ?? "GET").toUpperCase();
      if (url.startsWith("/api/v1/products") && method === "GET") {
        const rows = created ? [product, created] : [product];
        return new Response(JSON.stringify({ data: rows, meta: { page: 1, page_size: 20, total_items: rows.length, total_pages: 1 } }), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url === "/api/v1/products" && method === "POST") {
        created = { ...product, id: 2, sku: "SKU-2", name: "کالای جدید", sale_price: "120000.50" };
        return new Response(JSON.stringify({ data: created }), { status: 201, headers: { "Content-Type": "application/json" } });
      }
      throw new Error(`Unexpected request: ${method} ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderPage();
    expect(await screen.findByText("کالای نمونه")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "افزودن کالا" }));
    fireEvent.change(screen.getByLabelText("کد کالا (SKU)"), { target: { value: "SKU-2" } });
    fireEvent.change(screen.getByLabelText("نام کالا"), { target: { value: "کالای جدید" } });
    fireEvent.change(screen.getByLabelText("قیمت فروش"), { target: { value: "120000.50" } });
    fireEvent.click(screen.getByRole("button", { name: "ثبت کالا" }));
    expect(await screen.findByText("کالای جدید")).toBeTruthy();
    const createCall = fetchMock.mock.calls.find(([url, init]) => String(url) === "/api/v1/products" && init?.method === "POST");
    expect(JSON.parse(String(createCall?.[1]?.body))).toMatchObject({ sku: "SKU-2", name: "کالای جدید", sale_price: "120000.50", purchase_cost: null });
    expect(createCall?.[1]?.credentials).toBe("same-origin");
  });
});
