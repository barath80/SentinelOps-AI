"use client";
import Link from "next/link";
import { useState } from "react";

export default function ForgotPasswordForm() {
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);

  async function submit(form: FormData) {
    setBusy(true);
    await fetch("/api/auth/forgot-password", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ email: form.get("email") }),
    }).catch(() => null);
    setBusy(false);
    setSent(true); // Always show the same message, whether or not the email exists.
  }

  return (
    <div className="mx-auto max-w-sm">
      <div className="rounded-lg border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-900">
        <h1 className="text-2xl font-semibold">Reset your password</h1>
        {sent ? (
          <p className="mt-4 text-sm text-zinc-600 dark:text-zinc-300">
            If an account exists for that email, we&apos;ve sent a link to reset your password.
          </p>
        ) : (
          <form action={submit} className="mt-4 space-y-3">
            <label className="block text-sm font-medium">Email
              <input name="email" type="email" required maxLength={254} autoComplete="email" className="mt-1 w-full rounded border border-zinc-300 bg-white px-3 py-2 dark:bg-zinc-800" />
            </label>
            <button disabled={busy} className="w-full rounded-md bg-amber-400 py-2 font-semibold text-zinc-900 hover:bg-amber-300 disabled:opacity-60">
              {busy ? "Please wait…" : "Send reset link"}
            </button>
          </form>
        )}
      </div>
      <p className="mt-4 text-center text-sm"><Link href="/login" className="text-sky-700 hover:underline">Back to sign in</Link></p>
    </div>
  );
}
