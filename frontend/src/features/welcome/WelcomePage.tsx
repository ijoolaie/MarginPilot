import { useQuery } from "@tanstack/react-query";
import { fetchBackendStatus } from "../../lib/api";

type Status = "loading" | "success" | "error";

function StatusBadge({ status }: { status: Status }) {
  if (status === "loading") {
    return (
      <p
        data-testid="backend-status"
        className="rounded-lg bg-slate-100 px-4 py-2 text-slate-600"
        role="status"
      >
        در حال بررسی اتصال به سرور…
      </p>
    );
  }
  if (status === "success") {
    return (
      <p
        data-testid="backend-status"
        className="rounded-lg bg-emerald-100 px-4 py-2 text-emerald-800"
        role="status"
      >
        اتصال به سرور برقرار است.
      </p>
    );
  }
  return (
    <p
      data-testid="backend-status"
      className="rounded-lg bg-red-100 px-4 py-2 text-red-800"
      role="status"
    >
      خطا در اتصال به سرور — سرویس Backend در دسترس نیست.
    </p>
  );
}

export function WelcomePage() {
  const { isPending, isError } = useQuery({
    queryKey: ["backend-ready"],
    queryFn: ({ signal }) => fetchBackendStatus(signal),
    refetchInterval: 10_000,
  });

  const status: Status = isPending ? "loading" : isError ? "error" : "success";

  return (
    <main className="mx-auto flex min-h-screen max-w-xl flex-col items-center justify-center gap-6 p-6 text-center">
      <h1 className="text-3xl font-extrabold text-slate-900">MarginPilot</h1>
      <p className="text-slate-600">
        پلتفرم تحلیل سود واقعی کالاها — نسخهٔ زیرساخت (Phase 2 / Step 1).
      </p>
      <StatusBadge status={status} />
    </main>
  );
}
