import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router";
import { ComparisonDetailPage } from "./ComparisonDetailPage";
import { clearCsrfToken } from "../../lib/api";

const run = {
  id: 55, status: "pending_confirmation", summary: { total_matches: 1, matched: 1, uncertain: 1, increased: 0, decreased: 0 },
  base_list: { id: 11, title: "لیست مبنا", received_at: "2026-11-20", supplier: { name: "تأمین‌کننده اول" } },
  target_list: { id: 22, title: "لیست هدف", received_at: "2026-11-21", supplier: { name: "تأمین‌کننده دوم" } },
  matches: [{ id: 101, base_price_id: 201, target_price_id: 202, base_raw_name: "کالای نمونه", target_raw_name: "کالای نمونه جدید", base_price: { id: 201, sku: "A1", raw_name: "کالای نمونه", unit_price: "100", unit: "piece", currency: "IRT" }, target_price: { id: 202, sku: "A1", raw_name: "کالای نمونه جدید", unit_price: "120", unit: "piece", currency: "IRT" }, match_type: "uncertain", status: "pending", suggested_product_id: 5, confirmed_product_id: null, price_delta: "20", price_delta_pct: "20.0000" }],
};
function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  client.setQueryData(["auth", "me"], { user: { id: 1, email: "owner@example.com", full_name: "Owner", is_platform_admin: false }, memberships: [], active_tenant: { id: 7, name: "فروشگاه", role: "owner", permissions: ["comparison:read", "comparison:write"] } });
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/comparison/55"]}><Routes><Route path="/comparison/:runId" element={<ComparisonDetailPage />} /></Routes></MemoryRouter></QueryClientProvider>);
}

afterEach(() => { cleanup(); clearCsrfToken(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("comparison review", () => {
  it("confirms an ambiguous paired match against a selected product", async () => {
    let confirmed = false;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method ?? "GET").toUpperCase();
      if (url.includes("/comparison/runs/55?") && method === "GET") { const currentRun = confirmed ? { ...run, status: "completed", summary: { ...run.summary, uncertain: 0 }, matches: run.matches.map((match) => ({ ...match, status: "confirmed" })) } : run; return new Response(JSON.stringify({ data: currentRun, meta: { page: 1, page_size: 200, total_items: 1 } }), { status: 200, headers: { "Content-Type": "application/json" } }); }
      if (url === "/api/v1/price-lists/11") return new Response(JSON.stringify({ data: { id: 11, title: "لیست مبنا", items: [run.matches[0].base_price] } }), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/v1/price-lists/22") return new Response(JSON.stringify({ data: { id: 22, title: "لیست هدف", items: [run.matches[0].target_price] } }), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url.startsWith("/api/v1/products?")) return new Response(JSON.stringify({ data: [{ id: 5, sku: "A1", name: "کالای اصلی", unit: "piece", is_active: true }] }), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/v1/comparison/runs/55/confirm-matches" && method === "POST") {
        expect(JSON.parse(String(init?.body))).toEqual({ decisions: [{ match_id: 101, decision: "confirm", product_id: 5 }] }); confirmed = true;
        return new Response(JSON.stringify({ data: { run_id: 55, status: "completed", confirmed: 1, rejected: 0, pending: 0 } }), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      throw new Error(`Unexpected request: ${method} ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderPage();
    expect(await screen.findByText("کالای نمونه جدید")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("تصمیم"), { target: { value: "confirm" } });
    fireEvent.click(screen.getByRole("button", { name: "ثبت تصمیم‌های انتخاب‌شده" }));
    expect(await screen.findByText("تأییدشده")).toBeTruthy();
  });
  it("pairs ambiguous one-sided rows without submitting the peer row twice", async () => {
    const base = { id: 201, sku: "A1", raw_name: "کالای مبنا", unit_price: "100", unit: "piece", currency: "IRT" };
    const target = { id: 202, sku: "A1", raw_name: "کالای هدف", unit_price: "120", unit: "piece", currency: "IRT" };
    const oneSidedRun = { ...run, matches: [
      { ...run.matches[0], id: 101, base_price_id: 201, target_price_id: null, base_raw_name: base.raw_name, target_raw_name: null, base_price: base, target_price: null, match_type: "uncertain", status: "pending" },
      { ...run.matches[0], id: 102, base_price_id: null, target_price_id: 202, base_raw_name: null, target_raw_name: target.raw_name, base_price: null, target_price: target, match_type: "uncertain", status: "pending" },
    ] };
    let paired = false;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method ?? "GET").toUpperCase();
      if (url.includes("/comparison/runs/55?") && method === "GET") {
        const current = paired ? { ...oneSidedRun, status: "completed", matches: [{ ...oneSidedRun.matches[0], target_price_id: 202, target_raw_name: target.raw_name, target_price: target, status: "confirmed", price_delta: "20", price_delta_pct: "20.0000" }] } : oneSidedRun;
        return new Response(JSON.stringify({ data: current, meta: { page: 1, page_size: 200, total_items: current.matches.length } }), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url === "/api/v1/price-lists/11") return new Response(JSON.stringify({ data: { id: 11, title: "لیست مبنا", items: [base] } }), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/v1/price-lists/22") return new Response(JSON.stringify({ data: { id: 22, title: "لیست هدف", items: [target] } }), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url.startsWith("/api/v1/products?")) return new Response(JSON.stringify({ data: [{ id: 5, sku: "A1", name: "کالای اصلی", unit: "piece", is_active: true }] }), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url === "/api/v1/comparison/runs/55/confirm-matches" && method === "POST") {
        expect(JSON.parse(String(init?.body))).toEqual({ decisions: [{ match_id: 101, decision: "confirm", product_id: 5, peer_price_id: 202 }] });
        paired = true;
        return new Response(JSON.stringify({ data: { run_id: 55, status: "completed", confirmed: 1, rejected: 0, pending: 0 } }), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      throw new Error(`Unexpected request: ${method} ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderPage();
    await screen.findAllByText("کالای مبنا");
    fireEvent.change(screen.getAllByLabelText("تصمیم")[0]!, { target: { value: "confirm" } });
    fireEvent.change(screen.getAllByLabelText("قیمت همتای لیست دیگر")[0]!, { target: { value: "202" } });
    fireEvent.click(screen.getByRole("button", { name: "ثبت تصمیم‌های انتخاب‌شده" }));
    expect(await screen.findByText("تأییدشده")).toBeTruthy();
  });
});





