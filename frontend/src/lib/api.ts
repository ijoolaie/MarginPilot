/** Backend connectivity probe — relative paths so Caddy/proxy routing decides
 * where `/api` goes in every environment (dev proxy, compose, production). */

export type BackendStatus = {
  ready: boolean;
};

export async function fetchBackendStatus(
  signal?: AbortSignal,
): Promise<BackendStatus> {
  const response = await fetch("/api/health/ready", { signal });
  if (!response.ok) {
    throw new Error(`backend not ready (HTTP ${response.status})`);
  }
  const body = (await response.json()) as { status?: string };
  if (body.status !== "ready") {
    throw new Error("backend reports not ready");
  }
  return { ready: true };
}
