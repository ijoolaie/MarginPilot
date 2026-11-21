import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router";
import { ProtectedApp } from "./ProtectedApp";
import { clearCsrfToken } from "../../lib/api";

function authPayload(active: boolean) {
  return {
    user: { id: 1, email: "owner@example.com", full_name: "مدیر فروشگاه", is_platform_admin: false },
    memberships: [{ tenant_id: 10, tenant_name: "فروشگاه نمونه", role: "owner" }],
    active_tenant: active ? { id: 10, name: "فروشگاه نمونه", role: "owner", permissions: ["analytics:read"] } : null,
  };
}

afterEach(() => { cleanup(); clearCsrfToken(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("protected tenant workspace", () => {
  it("activates a selected tenant with the CSRF token and opens the workspace", async () => {
    let meCalls = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method ?? "GET").toUpperCase();
      if (url.endsWith("/auth/me")) {
        meCalls += 1;
        return new Response(JSON.stringify(authPayload(meCalls > 1)), { status: 200, headers: { "Content-Type": "application/json", "X-CSRF-Token": `csrf-${meCalls}` } });
      }
      if (url.endsWith("/tenants") && method === "GET") {
        return new Response(JSON.stringify({ data: [{ id: 10, name: "فروشگاه نمونه", slug: "sample", currency_code: "IRT", role: "owner", active: false }] }), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url.endsWith("/tenants/10/activate") && method === "POST") return new Response(null, { status: 204 });
      throw new Error(`Unexpected request: ${method} ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/"]}><Routes><Route element={<ProtectedApp />}><Route path="/" element={<h1>فضای کاری فعال</h1>} /></Route></Routes></MemoryRouter></QueryClientProvider>);

    fireEvent.click(await screen.findByRole("button", { name: /فروشگاه نمونه/ }));
    expect(await screen.findByRole("heading", { name: "فضای کاری فعال" })).toBeTruthy();
    const activationCall = fetchMock.mock.calls.find(([url, init]) => String(url).endsWith("/tenants/10/activate") && init?.method === "POST");
    expect(activationCall).toBeTruthy();
    expect(new Headers(activationCall?.[1]?.headers).get("X-CSRF-Token")).toBe("csrf-1");
    await waitFor(() => expect(meCalls).toBeGreaterThan(1));
  });
});
