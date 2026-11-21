import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router";
import { ComparisonListPage } from "./ComparisonListPage";
import { clearCsrfToken } from "../../lib/api";

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  client.setQueryData(["auth", "me"], { user: { id: 1, email: "owner@example.com", full_name: "Owner", is_platform_admin: false }, memberships: [], active_tenant: { id: 7, name: "فروشگاه", role: "owner", permissions: ["comparison:read", "comparison:write"] } });
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/comparison"]}><Routes><Route path="/comparison" element={<ComparisonListPage />} /><Route path="/comparison/:id" element={<h1>مقایسه ساخته شد</h1>} /></Routes></MemoryRouter></QueryClientProvider>);
}

afterEach(() => { cleanup(); clearCsrfToken(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("comparison creation", () => {
  it("creates a comparison from two finalized price lists with an idempotency key", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method ?? "GET").toUpperCase();
      if (url.startsWith("/api/v1/suppliers?") && method === "GET") return new Response(JSON.stringify({ data: [{ id: 1, name: "تأمین‌کننده اول" }, { id: 2, name: "تأمین‌کننده دوم" }] }), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url.includes("/suppliers/1/price-lists")) return new Response(JSON.stringify({ data: [{ id: 11, title: "لیست اول", received_at: "2026-11-20", status: "final" }] }), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url.includes("/suppliers/2/price-lists")) return new Response(JSON.stringify({ data: [{ id: 22, title: "لیست دوم", received_at: "2026-11-21", status: "final" }] }), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url.startsWith("/api/v1/comparison/runs?") && method === "GET") return new Response(JSON.stringify({ data: [], meta: { page: 1, page_size: 25, total_items: 0 } }), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/v1/comparison/runs" && method === "POST") {
        expect(new Headers(init?.headers).get("Idempotency-Key")).toBeTruthy();
        expect(JSON.parse(String(init?.body))).toMatchObject({ base_list_id: 11, target_list_id: 22, match_strategy: "sku_then_name" });
        return new Response(JSON.stringify({ data: { id: 55 } }), { status: 201, headers: { "Content-Type": "application/json" } });
      }
      throw new Error(`Unexpected request: ${method} ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderPage();
    await screen.findAllByRole("option", { name: "تأمین‌کننده اول" });
    fireEvent.change(screen.getByLabelText("تأمین‌کننده مبنا"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("تأمین‌کننده هدف"), { target: { value: "2" } });
    await screen.findByRole("option", { name: /لیست اول/ });
    await screen.findByRole("option", { name: /لیست دوم/ });
    fireEvent.change(screen.getByLabelText("لیست قیمت مبنا"), { target: { value: "11" } });
    fireEvent.change(screen.getByLabelText("لیست قیمت هدف"), { target: { value: "22" } });
    fireEvent.click(screen.getByRole("button", { name: "ایجاد مقایسه" }));
    expect(await screen.findByRole("heading", { name: "مقایسه ساخته شد" })).toBeTruthy();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/v1/comparison/runs", expect.objectContaining({ method: "POST" })));
  });
});


