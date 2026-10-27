"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";

export default function ProfileForm({ name, email }: { name: string; email: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ type: "ok" | "error"; text: string } | null>(null);

  async function submit(form: FormData) {
    setBusy(true);
    setMessage(null);
    const res = await fetch("/api/account", {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name: form.get("name"), email: form.get("email") }),
    }).catch(() => null);
    const body = res ? await res.json().catch(() => ({})) : {};
    setBusy(false);
    if (res?.ok) {
      setMessage({ type: "ok", text: "Profile updated." });
      router.refresh();
      return;
    }
    setMessage({ type: "error", text: body.message ?? "Something went wrong. Please try again." });
  }

  return (
    <section className="rounded-lg bg-white p-5 dark:bg-zinc-900">
      <h2 className="text-lg font-bold">Profile</h2>
      <form action={submit} className="mt-3 space-y-3">
        <label className="block text-sm font-medium">Name
          <input name="name" required maxLength={60} defaultValue={name} autoComplete="name" className="mt-1 w-full rounded border border-zinc-300 bg-white px-3 py-2 dark:bg-zinc-800" />
        </label>
        <label className="block text-sm font-medium">Email
          <input name="email" type="email" required maxLength={254} defaultValue={email} autoComplete="email" className="mt-1 w-full rounded border border-zinc-300 bg-white px-3 py-2 dark:bg-zinc-800" />
        </label>
        {message && <p role="alert" className={`text-sm ${message.type === "ok" ? "text-emerald-700 dark:text-emerald-400" : "text-red-600"}`}>{message.text}</p>}
        <button disabled={busy} className="rounded-full bg-amber-400 px-5 py-2 font-semibold text-zinc-900 hover:bg-amber-300 disabled:opacity-60">
          {busy ? "Saving…" : "Save changes"}
        </button>
      </form>
    </section>
  );
}
