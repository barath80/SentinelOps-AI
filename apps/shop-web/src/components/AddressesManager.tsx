"use client";
import { useState } from "react";

type Address = { id: string; label: string; fullName: string; line1: string; city: string; postalCode: string; country: string };

const FIELDS: { key: keyof Omit<Address, "id">; label: string }[] = [
  { key: "label", label: "Label (e.g. Home)" },
  { key: "fullName", label: "Full name" },
  { key: "line1", label: "Address" },
  { key: "city", label: "City" },
  { key: "postalCode", label: "Postal code" },
  { key: "country", label: "Country" },
];

export default function AddressesManager({ initial }: { initial: Address[] }) {
  const [addresses, setAddresses] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  async function add(form: FormData) {
    setBusy(true);
    setError(null);
    const payload = Object.fromEntries(FIELDS.map((f) => [f.key, String(form.get(f.key) ?? "")]));
    const res = await fetch("/api/account/addresses", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    }).catch(() => null);
    const body = res ? await res.json().catch(() => ({})) : {};
    setBusy(false);
    if (res?.ok) {
      setAddresses((prev) => [...prev, body.address]);
      setAdding(false);
      return;
    }
    setError("Please fill in every field.");
  }

  async function remove(id: string) {
    setAddresses((prev) => prev.filter((a) => a.id !== id));
    await fetch(`/api/account/addresses/${id}`, { method: "DELETE" }).catch(() => null);
  }

  return (
    <section className="rounded-lg bg-white p-5 dark:bg-zinc-900">
      <h2 className="text-lg font-bold">Addresses</h2>
      {addresses.length === 0 && !adding && <p className="mt-2 text-sm text-zinc-500">No saved addresses yet.</p>}
      <ul className="mt-3 space-y-3">
        {addresses.map((a) => (
          <li key={a.id} className="flex items-start justify-between gap-3 rounded border border-zinc-200 p-3 text-sm dark:border-zinc-800">
            <div>
              <p className="font-semibold">{a.label}</p>
              <p>{a.fullName}</p>
              <p className="text-zinc-500">{a.line1}, {a.city} {a.postalCode}, {a.country}</p>
            </div>
            <button type="button" onClick={() => remove(a.id)} className="text-sky-700 hover:underline">Remove</button>
          </li>
        ))}
      </ul>
      {adding ? (
        <form action={add} className="mt-4 grid gap-3 sm:grid-cols-2">
          {FIELDS.map((f) => (
            <label key={f.key} className={`text-sm ${f.key === "line1" ? "sm:col-span-2" : ""}`}>
              {f.label}
              <input name={f.key} required maxLength={120} className="mt-1 w-full rounded border border-zinc-300 bg-white px-3 py-2 dark:bg-zinc-800" />
            </label>
          ))}
          {error && <p role="alert" className="text-sm text-red-600 sm:col-span-2">{error}</p>}
          <div className="flex gap-2 sm:col-span-2">
            <button disabled={busy} className="rounded-full bg-amber-400 px-5 py-2 font-semibold text-zinc-900 hover:bg-amber-300 disabled:opacity-60">
              {busy ? "Saving…" : "Save address"}
            </button>
            <button type="button" onClick={() => setAdding(false)} className="rounded-full border border-zinc-300 px-5 py-2 font-semibold hover:bg-zinc-50 dark:border-zinc-700 dark:hover:bg-zinc-800">
              Cancel
            </button>
          </div>
        </form>
      ) : (
        <button type="button" onClick={() => setAdding(true)} className="mt-3 text-sm text-sky-700 hover:underline">
          + Add an address
        </button>
      )}
    </section>
  );
}
