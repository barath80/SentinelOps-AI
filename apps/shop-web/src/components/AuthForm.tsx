"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

const GOOGLE_ERRORS: Record<string, string> = {
  google_unavailable: "Google sign-in is not set up on this store yet. Use email and password.",
  google_state: "Google sign-in expired or was interrupted. Please try again.",
  google_rejected: "Google did not accept the sign-in. Please try again.",
  google_unverified: "Your Google account email is not verified, so it cannot be used here.",
  google_failed: "Google sign-in failed. Please try again.",
};

export default function AuthForm({ mode, next, error, google }: { mode: "login" | "signup"; next: string; error?: string; google: boolean }) {
  const router = useRouter();
  const [message, setMessage] = useState<string | null>(error ? GOOGLE_ERRORS[error] ?? "Sign-in failed." : null);
  const [busy, setBusy] = useState(false);

  async function submit(form: FormData) {
    setBusy(true);
    setMessage(null);
    const payload = Object.fromEntries(form.entries());
    const res = await fetch(`/api/auth/${mode}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    }).catch(() => null);
    const body = res ? await res.json().catch(() => ({})) : {};
    setBusy(false);
    if (res?.ok) {
      router.push(next);
      router.refresh();
      return;
    }
    setMessage(body.message ?? (body.error === "auth_not_configured" ? "Sign-in is not configured on this server yet." : "Something went wrong. Please try again."));
  }

  const other = mode === "login"
    ? <>New to ShopSphere? <Link href={`/signup?next=${encodeURIComponent(next)}`} className="text-sky-700 hover:underline">Create your account</Link></>
    : <>Already have an account? <Link href={`/login?next=${encodeURIComponent(next)}`} className="text-sky-700 hover:underline">Sign in</Link></>;

  return (
    <div className="mx-auto max-w-sm">
      <div className="rounded-lg border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-900">
        <h1 className="text-2xl font-semibold">{mode === "login" ? "Sign in" : "Create account"}</h1>
        {google && (
          <>
            <a href={`/api/auth/google?next=${encodeURIComponent(next)}`}
              className="mt-4 flex w-full items-center justify-center gap-2 rounded-md border border-zinc-300 bg-white py-2 font-medium text-zinc-800 hover:bg-zinc-50">
              <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true"><path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z" /><path fill="#FF3D00" d="m6.3 14.7 6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z" /><path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-8l-6.5 5C9.5 39.6 16.2 44 24 44z" /><path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.3-.1-2.4-.4-3.5z" /></svg>
              Continue with Google
            </a>
            <p className="my-4 text-center text-xs text-zinc-500">or use your email</p>
          </>
        )}
        <form action={submit} className={`${google ? "" : "mt-4"} space-y-3`}>
          {mode === "signup" && (
            <label className="block text-sm font-medium">Your name
              <input name="name" required maxLength={60} autoComplete="name" className="mt-1 w-full rounded border border-zinc-300 bg-white px-3 py-2 dark:bg-zinc-800" />
            </label>
          )}
          <label className="block text-sm font-medium">Email
            <input name="email" type="email" required maxLength={254} autoComplete="email" className="mt-1 w-full rounded border border-zinc-300 bg-white px-3 py-2 dark:bg-zinc-800" />
          </label>
          <label className="block text-sm font-medium">Password
            <input name="password" type="password" required minLength={mode === "signup" ? 8 : 1} maxLength={72}
              autoComplete={mode === "signup" ? "new-password" : "current-password"} className="mt-1 w-full rounded border border-zinc-300 bg-white px-3 py-2 dark:bg-zinc-800" />
          </label>
          {mode === "signup" && <p className="text-xs text-zinc-500">At least 8 characters.</p>}
          {mode === "login" && (
            <p className="text-right text-sm"><Link href="/forgot-password" className="text-sky-700 hover:underline">Forgot password?</Link></p>
          )}
          {message && <p role="alert" className="text-sm text-red-600">{message}</p>}
          <button disabled={busy} className="w-full rounded-md bg-amber-400 py-2 font-semibold text-zinc-900 hover:bg-amber-300 disabled:opacity-60">
            {busy ? "Please wait…" : mode === "login" ? "Sign in" : "Create your account"}
          </button>
        </form>
      </div>
      <p className="mt-4 text-center text-sm">{other}</p>
    </div>
  );
}
