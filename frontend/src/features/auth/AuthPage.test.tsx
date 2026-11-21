import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router";
import { AuthPage } from "./AuthPage";
import { clearCsrfToken } from "../../lib/api";

function renderPage(mode: "login" | "register" = "login") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><MemoryRouter><AuthPage mode={mode} /></MemoryRouter></QueryClientProvider>);
}

afterEach(() => { cleanup(); clearCsrfToken(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("authentication form", () => {
  it("submits credentials and displays a safe invalid-credentials message", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: { code: "INVALID_CREDENTIALS", message: "invalid", details: [] } }), { status: 401, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);
    renderPage();
    fireEvent.change(screen.getByLabelText("ایمیل"), { target: { value: "user@example.com" } });
    fireEvent.change(screen.getByLabelText("گذرواژه"), { target: { value: "incorrect-password" } });
    fireEvent.click(screen.getByRole("button", { name: "ورود" }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("ایمیل یا گذرواژه صحیح نیست");
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/auth/login", expect.objectContaining({ method: "POST", credentials: "same-origin" }));
  });

  it("requires the registration fields and a 12-character password", () => {
    renderPage("register");
    expect((screen.getByLabelText("نام و نام خانوادگی") as HTMLInputElement).required).toBe(true);
    expect((screen.getByLabelText("نام کسب‌وکار") as HTMLInputElement).required).toBe(true);
    expect((screen.getByLabelText("گذرواژه") as HTMLInputElement).minLength).toBe(12);
  });
});
