"use client";
import { useRef, useState } from "react";

export default function PasswordForm() {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ type: "ok" | "error"; text: string } | null>(null);
  const formRef = useRef<HTMLFormElement>(null);

  async function submit(form: FormData) {
    setBusy(true);
    setMessage(null);
    const res = await fetch("/api/account/password", {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ currentPassword: form.get("currentPassword"), newPassword: form.get("newPassword") }),
    }).catch(() => null);
    const body = res ? await res.json().catch(() => ({})) : {};
    setBusy(false);
    if (res?.ok) {
      setMessage({ type: "ok", text: "Password changed." });
      formRef.current?.reset();
      return;
    }
    setMessage({ type: "error", text: body.message ?? "Something went wrong. Please try again." });
  }

  return (
    <section className="rounded-lg bg-white p-5 dark:bg-zinc-900">
      <h2 className="text-lg font-bold">Password</h2>
      <form ref={formRef} action={submit} className="mt-3 space-y-3">
        <label className="block text-sm font-medium">Current password
          <input name="currentPassword" type="password" required maxLength={72} autoComplete="current-password" className="mt-1 w-full rounded border border-zinc-300 bg-white px-3 py-2 dark:bg-zinc-800" />
        </label>
        <label className="block text-sm font-medium">New password
          <input name="newPassword" type="password" required minLength={8} maxLength={72} autoComplete="new-password" className="mt-1 w-full rounded border border-zinc-300 bg-white px-3 py-2 dark:bg-zinc-800" />
        </label>
        {message && <p role="alert" className={`text-sm ${message.type === "ok" ? "text-emerald-700 dark:text-emerald-400" : "text-red-600"}`}>{message.text}</p>}
        <button disabled={busy} className="rounded-full bg-amber-400 px-5 py-2 font-semibold text-zinc-900 hover:bg-amber-300 disabled:opacity-60">
          {busy ? "Saving…" : "Change password"}
        </button>
      </form>
    </section>
  );
}
