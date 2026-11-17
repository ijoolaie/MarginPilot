import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { WelcomePage } from "./WelcomePage";

function renderPage(): void {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <WelcomePage />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup(); // vitest globals are off — no automatic RTL cleanup
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("WelcomePage backend status", () => {
  it("shows loading state first, then success when backend is ready", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve({ ok: true, json: () => Promise.resolve({ status: "ready" }) }),
      ),
    );
    renderPage();
    expect(screen.getByTestId("backend-status").textContent).toContain(
      "در حال بررسی",
    );
    await waitFor(() =>
      expect(screen.getByTestId("backend-status").textContent).toContain("برقرار است"),
    );
  });

  it("shows error state when backend is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new Error("network down"))));
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("backend-status").textContent).toContain("خطا"),
    );
  });

  it("shows error state when backend reports not ready (HTTP 503)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve({ ok: false, status: 503 })),
    );
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("backend-status").textContent).toContain("خطا"),
    );
  });
});
