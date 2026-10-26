"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { formatPrice } from "@/lib/products";

type Line = { product: { id: string; name: string }; qty: number; lineCents: number };
type CartView = { lines: Line[]; totalCents: number };

export default function CartPage() {
  const router = useRouter();
  const [cart, setCart] = useState<CartView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // One key per checkout attempt; retries of the same attempt reuse it.
  const idemKey = useRef<string | null>(null);

  const load = useCallback(async () => setCart(await fetch("/api/cart").then((r) => r.json())), []);
  useEffect(() => {
    let live = true;
    fetch("/api/cart")
      .then((r) => r.json())
      .then((c) => live && setCart(c));
    return () => {
      live = false;
    };
  }, []);

  async function setQty(id: string, qty: number) {
    await fetch("/api/cart", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ id, qty }),
    });
    await load();
  }

  async function checkout() {
    setBusy(true);
    setError(null);
    idemKey.current ??= crypto.randomUUID();
    const res = await fetch("/api/checkout", { method: "POST", headers: { "idempotency-key": idemKey.current } });
    const body = await res.json().catch(() => ({}));
    setBusy(false);
    if (res.ok) router.push(`/order/${body.order.id}`);
    else setError(body.error === "payment_declined" ? "Payment was declined." : "Checkout failed. Please try again.");
  }

  if (!cart) return <p>Loading…</p>;
  if (cart.lines.length === 0)
    return (
      <p>
        Your cart is empty.{" "}
        <Link href="/" className="underline">
          Browse products
        </Link>
      </p>
    );

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Cart</h1>
      <ul className="divide-y">
        {cart.lines.map((l) => (
          <li key={l.product.id} className="flex items-center justify-between py-3">
            <span>
              {l.product.name} × {l.qty}
            </span>
            <span className="flex items-center gap-3">
              {formatPrice(l.lineCents)}
              <button className="text-sm underline" onClick={() => setQty(l.product.id, 0)}>
                Remove
              </button>
            </span>
          </li>
        ))}
      </ul>
      <p className="text-lg font-medium">Total: {formatPrice(cart.totalCents)}</p>
      {error && (
        <p role="alert" className="text-red-600">
          {error}
        </p>
      )}
      <button
        onClick={checkout}
        disabled={busy}
        className="rounded bg-black px-4 py-2 text-white disabled:opacity-50 dark:bg-white dark:text-black"
      >
        {busy ? "Placing order…" : "Place simulated order"}
      </button>
    </div>
  );
}
