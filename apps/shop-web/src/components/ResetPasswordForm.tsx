"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

export default function ResetPasswordForm({ token }: { token: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  async function submit(form: FormData) {
    setBusy(true);
    setError(null);
    const res = await fetch("/api/auth/reset-password", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ token, password: form.get("password") }),
    }).catch(() => null);
    const body = res ? await res.json().catch(() => ({})) : {};
    setBusy(false);
    if (res?.ok) {
      setDone(true);
      setTimeout(() => router.push("/login"), 2000);
      return;
    }
    setError(body.message ?? (body.error === "invalid_or_expired_token" ? "This reset link is invalid or has expired." : "Something went wrong. Please try again."));
  }

  return (
    <div className="mx-auto max-w-sm">
      <div className="rounded-lg border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-900">
        <h1 className="text-2xl font-semibold">Choose a new password</h1>
        {done ? (
          <p className="mt-4 text-sm text-emerald-700 dark:text-emerald-400">Your password has been reset. Redirecting to sign in…</p>
        ) : (
          <form action={submit} className="mt-4 space-y-3">
            <label className="block text-sm font-medium">New password
              <input name="password" type="password" required minLength={8} maxLength={72} autoComplete="new-password"
                className="mt-1 w-full rounded border border-zinc-300 bg-white px-3 py-2 dark:bg-zinc-800" />
            </label>
            <p className="text-xs text-zinc-500">At least 8 characters.</p>
            {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
            <button disabled={busy} className="w-full rounded-md bg-amber-400 py-2 font-semibold text-zinc-900 hover:bg-amber-300 disabled:opacity-60">
              {busy ? "Please wait…" : "Reset password"}
            </button>
          </form>
        )}
      </div>
      <p className="mt-4 text-center text-sm"><Link href="/login" className="text-sky-700 hover:underline">Back to sign in</Link></p>
    </div>
  );
}
