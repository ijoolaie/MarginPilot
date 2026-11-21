import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SuppliersPage } from "./SuppliersPage";
import { clearCsrfToken } from "../../lib/api";

type SupplierRecord = { id: number; name: string; contact_name: string | null; phone: string | null; email: string | null; is_active: boolean };
const supplier: SupplierRecord = { id: 1, name: "تأمین‌کننده نمونه", contact_name: null, phone: "021123456", email: null, is_active: true };
function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  client.setQueryData(["auth", "me"], { user: { id: 1, email: "owner@example.com", full_name: "Owner", is_platform_admin: false }, memberships: [], active_tenant: { id: 7, name: "فروشگاه", role: "owner", permissions: ["supplier:read", "supplier:write"] } });
  render(<QueryClientProvider client={client}><SuppliersPage /></QueryClientProvider>);
}

afterEach(() => { cleanup(); clearCsrfToken(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("supplier directory", () => {
  it("lists suppliers and creates a tenant-scoped supplier", async () => {
    let created: SupplierRecord | null = null;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method ?? "GET").toUpperCase();
      if (url.startsWith("/api/v1/suppliers") && method === "GET") {
        const rows = created ? [supplier, created] : [supplier];
        return new Response(JSON.stringify({ data: rows, meta: { page: 1, page_size: 20, total_items: rows.length, total_pages: 1 } }), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url === "/api/v1/suppliers" && method === "POST") {
        created = { id: 2, name: "تأمین‌کننده جدید", contact_name: null, phone: null, email: "vendor@example.com", is_active: true };
        return new Response(JSON.stringify({ data: created }), { status: 201, headers: { "Content-Type": "application/json" } });
      }
      throw new Error(`Unexpected request: ${method} ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderPage();
    expect(await screen.findByText("تأمین‌کننده نمونه")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "افزودن تأمین‌کننده" }));
    fireEvent.change(screen.getByLabelText("نام تأمین‌کننده"), { target: { value: "تأمین‌کننده جدید" } });
    fireEvent.change(screen.getByLabelText("ایمیل"), { target: { value: "vendor@example.com" } });
    fireEvent.click(screen.getByRole("button", { name: "ثبت تأمین‌کننده" }));
    expect(await screen.findByText("تأمین‌کننده جدید")).toBeTruthy();
    const createCall = fetchMock.mock.calls.find(([url, init]) => String(url) === "/api/v1/suppliers" && init?.method === "POST");
    expect(JSON.parse(String(createCall?.[1]?.body))).toMatchObject({ name: "تأمین‌کننده جدید", email: "vendor@example.com" });
  });
});

