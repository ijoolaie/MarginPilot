import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ImportPage } from "./ImportPage";
import { clearCsrfToken } from "../../lib/api";

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  client.setQueryData(["auth", "me"], { user: { id: 1, email: "owner@example.com", full_name: "Owner", is_platform_admin: false }, memberships: [], active_tenant: { id: 7, name: "فروشگاه", role: "owner", permissions: ["import:execute", "import:read"] } });
  render(<QueryClientProvider client={client}><ImportPage /></QueryClientProvider>);
}

afterEach(() => { cleanup(); clearCsrfToken(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("two-phase import workflow", () => {
  it("uploads, maps, previews, and confirms only after explicit approval", async () => {
    const batch = { id: 41, kind: "products", status: "parsed", file_name: "products.csv", column_headers: ["sku", "name", "unit", "sale_price"], mapping: {}, stats: { total_rows: 1, valid_rows: 0, error_rows: 0, duplicate_rows: 0, skipped_rows: 0, committed_rows: 0 }, supplier_id: null, price_list_title: null, received_at: null };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method ?? "GET").toUpperCase();
      if (url === "/api/v1/imports" && method === "POST") {
        expect(init?.body).toBeInstanceOf(FormData);
        return new Response(JSON.stringify({ data: batch }), { status: 201, headers: { "Content-Type": "application/json" } });
      }
      if (url === "/api/v1/imports/41/mapping" && method === "PATCH") {
        const body = JSON.parse(String(init?.body));
        expect(body.mapping).toMatchObject({ sku: "sku", name: "name", unit: "unit", sale_price: "sale_price" });
        return new Response(JSON.stringify({ data: { ...batch, status: "awaiting_confirmation", mapping: body.mapping, stats: { ...batch.stats, valid_rows: 1 } }, preview: [{ row_number: 2, status: "valid", normalized: { sku: "A-1", name: "کالای نمونه", unit: "piece", sale_price: "120000.00" }, errors: [] }] }), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url === "/api/v1/imports/41/confirm" && method === "POST") {
        expect(new Headers(init?.headers).get("Idempotency-Key")).toBeTruthy();
        return new Response(JSON.stringify({ data: { status: "committed", committed_rows: 1, skipped_rows: 0, supplier_price_list_id: null } }), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      throw new Error(`Unexpected request: ${method} ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderPage();
    const file = new File([["sku,name,unit,sale_price", "A-1,کالای نمونه,piece,120000"].join(String.fromCharCode(10))], "products.csv", { type: "text/csv" });
    fireEvent.change(screen.getByLabelText("فایل CSV یا XLSX"), { target: { files: [file] } });
    const uploadButton = screen.getByRole("button", { name: "بارگذاری و بررسی فایل" });
    expect(uploadButton.hasAttribute("disabled")).toBe(false);
    fireEvent.submit(uploadButton.closest("form") as HTMLFormElement);
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(await screen.findByText("products.csv")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "اعتبارسنجی و پیش‌نمایش" }));
    expect(await screen.findByText(/کالای نمونه/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "تأیید و ثبت 1 ردیف معتبر" }));
    expect(await screen.findByText(/واردسازی ثبت شد/)).toBeTruthy();
  });
  it("finalizes the draft supplier price list created by a confirmed import", async () => {
    const batch = { id: 42, kind: "supplier_prices", status: "parsed", file_name: "vendor.csv", column_headers: ["raw_name", "unit_price", "unit"], mapping: {}, stats: { total_rows: 1, valid_rows: 0 }, supplier_id: 9, price_list_title: "لیست آبان", received_at: "2026-11-21" };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method ?? "GET").toUpperCase();
      if (url.startsWith("/api/v1/suppliers?") && method === "GET") return new Response(JSON.stringify({ data: [{ id: 9, name: "تأمین‌کننده نمونه" }] }), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/v1/imports" && method === "POST") return new Response(JSON.stringify({ data: batch }), { status: 201, headers: { "Content-Type": "application/json" } });
      if (url === "/api/v1/imports/42/mapping" && method === "PATCH") return new Response(JSON.stringify({ data: { ...batch, status: "awaiting_confirmation", stats: { total_rows: 1, valid_rows: 1 } }, preview: [{ row_number: 2, status: "valid", normalized: { raw_name: "کالای نمونه", unit_price: "500", unit: "piece" }, errors: [] }] }), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/v1/imports/42/confirm" && method === "POST") return new Response(JSON.stringify({ data: { status: "committed", committed_rows: 1, skipped_rows: 0, supplier_price_list_id: 88 } }), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/v1/price-lists/88/finalize" && method === "POST") return new Response(JSON.stringify({ data: { id: 88, status: "final", item_count: 1 } }), { status: 200, headers: { "Content-Type": "application/json" } });
      throw new Error(`Unexpected request: ${method} ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    client.setQueryData(["auth", "me"], { user: { id: 1, email: "owner@example.com", full_name: "Owner", is_platform_admin: false }, memberships: [], active_tenant: { id: 7, name: "فروشگاه", role: "owner", permissions: ["import:execute", "supplier:read"] } });
    render(<QueryClientProvider client={client}><ImportPage /></QueryClientProvider>);
    fireEvent.change(screen.getByLabelText("نوع اطلاعات"), { target: { value: "supplier_prices" } });
    await screen.findByRole("option", { name: "تأمین‌کننده نمونه" });
    fireEvent.change(screen.getByLabelText("تأمین‌کننده"), { target: { value: "9" } });
    fireEvent.change(screen.getByLabelText("عنوان لیست قیمت"), { target: { value: "لیست آبان" } });
    fireEvent.change(screen.getByLabelText("تاریخ دریافت"), { target: { value: "2026-11-21" } });
    const file = new File(["raw_name,unit_price,unit"], "vendor.csv", { type: "text/csv" });
    fireEvent.change(screen.getByLabelText("فایل CSV یا XLSX"), { target: { files: [file] } });
    fireEvent.submit(screen.getByRole("button", { name: "بارگذاری و بررسی فایل" }).closest("form") as HTMLFormElement);
    await screen.findByText("vendor.csv");
    fireEvent.click(screen.getByRole("button", { name: "اعتبارسنجی و پیش‌نمایش" }));
    await screen.findByText(/کالای نمونه/);
    fireEvent.click(screen.getByRole("button", { name: "تأیید و ثبت 1 ردیف معتبر" }));
    fireEvent.click(await screen.findByRole("button", { name: "نهایی‌سازی لیست قیمت" }));
    expect(await screen.findByText("لیست قیمت نهایی شد و آماده مقایسه است.")).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/price-lists/88/finalize", expect.objectContaining({ method: "POST" }));
  });
});




