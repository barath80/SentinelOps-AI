"use client";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import CheckoutSteps from "./CheckoutSteps";
import EmptyState from "./EmptyState";
import ProductArt from "./ProductArt";
import { Skeleton } from "./Skeleton";
import { formatPrice, type ArtKind } from "@/lib/products";

type Line = { product: { id: string; name: string; art: ArtKind }; color: { name: string; hex: string }; qty: number; lineCents: number };
type CartView = { lines: Line[]; totalCents: number; count: number };

const FIELDS: { key: string; label: string; autoComplete: string }[] = [
  { key: "fullName", label: "Full name", autoComplete: "name" },
  { key: "line1", label: "Address", autoComplete: "address-line1" },
  { key: "city", label: "City", autoComplete: "address-level2" },
  { key: "postalCode", label: "Postal code", autoComplete: "postal-code" },
  { key: "country", label: "Country", autoComplete: "country-name" },
];

export default function CheckoutForm({ defaultName }: { defaultName: string }) {
  const router = useRouter();
  const [cart, setCart] = useState<CartView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // One key per checkout attempt; retries of the same attempt reuse it, so no duplicate orders.
  const idemKey = useRef<string | null>(null);

  useEffect(() => {
    let live = true;
    fetch("/api/cart").then((r) => r.json()).then((c) => live && setCart(c));
    return () => { live = false; };
  }, []);

  async function place(form: FormData) {
    setBusy(true);
    setError(null);
    idemKey.current ??= crypto.randomUUID();
    const shipping = Object.fromEntries(FIELDS.map((f) => [f.key, String(form.get(f.key) ?? "")]));
    const res = await fetch("/api/checkout", {
      method: "POST",
      headers: { "idempotency-key": idemKey.current, "content-type": "application/json" },
      body: JSON.stringify({ shipping }),
    }).catch(() => null);
    const body = res ? await res.json().catch(() => ({})) : {};
    setBusy(false);
    if (res?.ok) {
      router.push(`/order/${body.order.id}`);
      router.refresh();
      return;
    }
    setError(
      body.error === "payment_declined" ? "Your payment was declined." :
      body.error === "payment_timeout" ? "The payment service did not respond. Please try again." :
      body.error === "invalid_shipping" ? "Please fill in every address field." :
      body.error === "cart_empty" ? "Your cart is empty." : "Something went wrong placing your order. Please try again.",
    );
  }

  if (!cart) {
    return (
      <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
        <div className="space-y-3 rounded-lg bg-white p-5 dark:bg-zinc-900">
          <Skeleton className="h-6 w-32" />
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
        <Skeleton className="h-48 w-full rounded-lg" />
      </div>
    );
  }
  if (cart.lines.length === 0) {
    return (
      <EmptyState
        title="Your cart is empty"
        message="Add something to your cart before checking out."
        action={{ href: "/", label: "Continue shopping" }}
      />
    );
  }

  return (
    <form action={place} className="grid gap-6 lg:grid-cols-[1fr_320px]">
      <section className="rounded-lg bg-white p-5 dark:bg-zinc-900">
        <h1 className="text-2xl font-bold">Checkout</h1>
        <div className="mt-3">
          <CheckoutSteps current={error ? 1 : busy ? 2 : 1} />
        </div>
        <h2 className="mt-5 font-semibold">1. Delivery address</h2>
        <div className="mt-2 grid gap-3 sm:grid-cols-2">
          {FIELDS.map((f) => (
            <label key={f.key} className={`text-sm ${f.key === "line1" ? "sm:col-span-2" : ""}`}>
              {f.label}
              <input name={f.key} required maxLength={120} autoComplete={f.autoComplete} defaultValue={f.key === "fullName" ? defaultName : ""}
                className="mt-1 w-full rounded border border-zinc-300 bg-white px-3 py-2 dark:bg-zinc-800" />
            </label>
          ))}
        </div>
        <h2 className="mt-6 font-semibold">2. Payment</h2>
        <p className="mt-1 rounded bg-amber-50 p-3 text-sm text-amber-900">Demo store: payment is simulated. Do not enter card details anywhere.</p>
        <h2 className="mt-6 font-semibold">3. Review items</h2>
        <ul className="mt-2 divide-y divide-zinc-200 dark:divide-zinc-800">
          {cart.lines.map((l) => (
            <li key={`${l.product.id}-${l.color.name}`} className="flex items-center gap-3 py-2">
              <ProductArt kind={l.product.art} color={l.color.hex} label={l.product.name} className="h-14 w-14 rounded" />
              <span className="flex-1 text-sm">{l.product.name} <span className="text-zinc-500">({l.color.name}) × {l.qty}</span></span>
              <span className="text-sm font-semibold">{formatPrice(l.lineCents)}</span>
            </li>
          ))}
        </ul>
      </section>
      <aside className="h-fit rounded-lg bg-white p-5 dark:bg-zinc-900">
        <button disabled={busy} className="w-full rounded-full bg-amber-400 py-2 font-semibold text-zinc-900 hover:bg-amber-300 disabled:opacity-60">
          {busy ? "Placing your order…" : "Place your order"}
        </button>
        <dl className="mt-4 space-y-1 text-sm">
          <div className="flex justify-between"><dt>Items ({cart.count})</dt><dd>{formatPrice(cart.totalCents)}</dd></div>
          <div className="flex justify-between"><dt>Delivery</dt><dd className="text-emerald-700">FREE</dd></div>
          <div className="flex justify-between border-t border-zinc-200 pt-2 text-lg font-semibold dark:border-zinc-800"><dt>Order total</dt><dd>{formatPrice(cart.totalCents)}</dd></div>
        </dl>
        {error && <p role="alert" className="mt-3 text-sm text-red-600">{error}</p>}
      </aside>
    </form>
  );
}
