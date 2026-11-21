export type ApiErrorPayload = { error?: { code?: string; message?: string; details?: Array<{ field?: string | null; issue: string }> } };

export class ApiError extends Error {
  constructor(message: string, readonly status: number, readonly code: string, readonly details: Array<{ field?: string | null; issue: string }> = []) {
    super(message);
    this.name = "ApiError";
  }
}

let csrfToken: string | null = null;
export function clearCsrfToken(): void { csrfToken = null; }

export async function apiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  if (!["GET", "HEAD", "OPTIONS"].includes(method) && csrfToken) headers.set("X-CSRF-Token", csrfToken);
  const response = await fetch(path, { ...init, method, headers, credentials: "same-origin" });
  const rotatedToken = response.headers.get("X-CSRF-Token");
  if (rotatedToken) csrfToken = rotatedToken;
  if (!response.ok) {
    const payload = (await response.json().catch(() => ({}))) as ApiErrorPayload;
    const error = payload.error;
    throw new ApiError(error?.message ?? "ارتباط با سرور ناموفق بود.", response.status, error?.code ?? "REQUEST_FAILED", error?.details ?? []);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  get: <T>(path: string) => apiRequest<T>(path),
  post: <T>(path: string, body?: unknown) => apiRequest<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) }),
};
