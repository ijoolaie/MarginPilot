import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";
import { ApiError, api } from "../../lib/api";

type Mode = "login" | "register";
type AuthResponse = { user: { id: number; email: string; full_name: string } };
const messages: Record<string, string> = {
  INVALID_CREDENTIALS: "ایمیل یا گذرواژه صحیح نیست.",
  ACCOUNT_TEMPORARILY_LOCKED: "حساب موقتاً قفل شده است. کمی بعد دوباره تلاش کنید.",
  RATE_LIMITED: "تعداد تلاش‌ها بیش از حد مجاز است. کمی بعد دوباره تلاش کنید.",
  REGISTRATION_CLOSED: "ثبت‌نام عمومی در حال حاضر غیرفعال است.",
  EMAIL_ALREADY_REGISTERED: "این ایمیل قبلاً ثبت شده است.",
  PASSWORD_POLICY_VIOLATION: "گذرواژه باید شرایط امنیتی سامانه را داشته باشد.",
};

export function AuthPage({ mode }: { mode: Mode }) {
  const isRegister = mode === "register";
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [tenantName, setTenantName] = useState("");
  const [currency, setCurrency] = useState<"IRT" | "IRR">("IRT");
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () => api.post<AuthResponse>(
      isRegister ? "/api/v1/auth/register" : "/api/v1/auth/login",
      isRegister ? { email, password, full_name: fullName, tenant_name: tenantName, currency_code: currency } : { email, password },
    ),
    onSuccess: async () => {
      setError(null);
      queryClient.clear();
      await navigate("/");
    },
    onError: (cause: unknown) => setError(cause instanceof ApiError ? messages[cause.code] ?? cause.message : "ارتباط با سرور برقرار نشد. دوباره تلاش کنید."),
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    mutation.mutate();
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-50 px-4 py-10" dir="rtl">
      <section className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-7 shadow-sm">
        <div className="mb-7 text-center">
          <p className="text-sm font-semibold text-teal-700">MarginPilot</p>
          <h1 className="mt-2 text-2xl font-bold text-slate-900">{isRegister ? "ساخت حساب و کسب‌وکار" : "ورود به حساب کاربری"}</h1>
          <p className="mt-2 text-sm text-slate-500">تحلیل سود واقعی و تصمیم‌گیری مطمئن‌تر</p>
        </div>
        <form className="space-y-4" onSubmit={submit}>
          {isRegister && <>
            <Field label="نام و نام خانوادگی" value={fullName} onChange={setFullName} required autoComplete="name" />
            <Field label="نام کسب‌وکار" value={tenantName} onChange={setTenantName} required />
          </>}
          <Field label="ایمیل" type="email" value={email} onChange={setEmail} required autoComplete="email" />
          <Field label="گذرواژه" type="password" value={password} onChange={setPassword} required autoComplete={isRegister ? "new-password" : "current-password"} minLength={isRegister ? 12 : 1} />
          {isRegister && <label className="block text-sm font-medium text-slate-700">واحد پول کسب‌وکار
            <select className="mt-1.5 w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5" value={currency} onChange={(event) => setCurrency(event.target.value as "IRT" | "IRR")}>
              <option value="IRT">تومان (IRT)</option><option value="IRR">ریال (IRR)</option>
            </select>
          </label>}
          {error && <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
          <button className="w-full rounded-lg bg-teal-700 px-4 py-3 font-semibold text-white transition hover:bg-teal-800 disabled:cursor-not-allowed disabled:opacity-60" type="submit" disabled={mutation.isPending}>
            {mutation.isPending ? "لطفاً صبر کنید…" : isRegister ? "ایجاد حساب" : "ورود"}
          </button>
        </form>
        <p className="mt-6 text-center text-sm text-slate-600">{isRegister ? "قبلاً حساب ساخته‌اید؟ " : "حساب کاربری ندارید؟ "}
          <Link className="font-semibold text-teal-700 hover:underline" to={isRegister ? "/login" : "/register"}>{isRegister ? "ورود" : "ثبت‌نام"}</Link>
        </p>
      </section>
    </main>
  );
}

function Field({ label, value, onChange, type = "text", required = false, autoComplete, minLength }: {
  label: string; value: string; onChange: (value: string) => void; type?: string; required?: boolean; autoComplete?: string; minLength?: number;
}) {
  return <label className="block text-sm font-medium text-slate-700">{label}
    <input className="mt-1.5 w-full rounded-lg border border-slate-300 px-3 py-2.5 outline-none transition focus:border-teal-600 focus:ring-2 focus:ring-teal-100" type={type} value={value} onChange={(event) => onChange(event.target.value)} required={required} autoComplete={autoComplete} minLength={minLength} />
  </label>;
}

