import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, clearCsrfToken } from "./api";

afterEach(() => {
  clearCsrfToken();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("same-origin API client", () => {
  it("keeps the CSRF token in memory and attaches it to unsafe requests", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ user: { id: 1 } }), { status: 200, headers: { "Content-Type": "application/json", "X-CSRF-Token": "csrf-one" } }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    await api.get("/api/v1/auth/me");
    await api.post("/api/v1/tenants/7/activate");

    expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({ credentials: "same-origin", method: "GET" });
    const mutationHeaders = new Headers(fetchMock.mock.calls[1]?.[1]?.headers);
    expect(mutationHeaders.get("X-CSRF-Token")).toBe("csrf-one");
  });

  it("updates the in-memory token when the server rotates it", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response("{}", { status: 200, headers: { "Content-Type": "application/json", "X-CSRF-Token": "csrf-new" } }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    await api.get("/api/v1/auth/me");
    await api.post("/api/v1/auth/logout");

    expect(new Headers(fetchMock.mock.calls[1]?.[1]?.headers).get("X-CSRF-Token")).toBe("csrf-new");
  });

  it("normalizes the backend error envelope", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: { code: "INVALID_CREDENTIALS", message: "invalid", details: [] } }), { status: 401, headers: { "Content-Type": "application/json" } })));
    await expect(api.get("/api/v1/auth/me")).rejects.toMatchObject({ status: 401, code: "INVALID_CREDENTIALS" } satisfies Partial<ApiError>);
  });
});
