"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import EmptyState from "@/components/EmptyState";
import ProductArt from "@/components/ProductArt";
import { Skeleton } from "@/components/Skeleton";
import { formatPrice, type ArtKind } from "@/lib/products";

type Line = { product: { id: string; name: string; brand: string; art: ArtKind; stock: number }; color: { name: string; hex: string }; qty: number; lineCents: number };
type CartView = { lines: Line[]; totalCents: number; count: number };

export default function CartPage() {
  const router = useRouter();
  const [cart, setCart] = useState<CartView | null>(null);

  useEffect(() => {
    let live = true;
    fetch("/api/cart").then((r) => r.json()).then((c) => live && setCart(c));
    return () => { live = false; };
  }, []);

  async function setQty(l: Line, qty: number) {
    const res = await fetch("/api/cart", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ id: l.product.id, color: l.color.name, qty }),
    });
    if (res.ok) {
      setCart(await res.json());
      router.refresh();
    }
  }

  if (!cart) {
    return (
      <div className="grid gap-6 lg:grid-cols-[1fr_300px]">
        <section className="space-y-4 rounded-lg bg-white p-5 dark:bg-zinc-900">
          <Skeleton className="h-6 w-40" />
          {Array.from({ length: 2 }, (_, i) => (
            <div key={i} className="flex gap-4">
              <Skeleton className="h-28 w-28 rounded-md" />
              <div className="flex-1 space-y-2">
                <Skeleton className="h-4 w-2/3" />
                <Skeleton className="h-3 w-1/3" />
                <Skeleton className="h-3 w-1/4" />
              </div>
            </div>
          ))}
        </section>
        <Skeleton className="h-40 w-full rounded-lg" />
      </div>
    );
  }
  if (cart.lines.length === 0)
    return (
      <EmptyState
        title="Your cart is empty"
        message={
          <>
            <Link href="/deals" className="text-sky-700 hover:underline">Shop today&apos;s deals</Link> or{" "}
            <Link href="/" className="text-sky-700 hover:underline">continue browsing</Link>.
          </>
        }
        action={{ href: "/", label: "Continue shopping" }}
      />
    );

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_300px]">
      <section className="rounded-lg bg-white p-5 dark:bg-zinc-900">
        <h1 className="text-2xl font-bold">Shopping cart</h1>
        <ul className="mt-3 divide-y divide-zinc-200 dark:divide-zinc-800">
          {cart.lines.map((l) => (
            <li key={`${l.product.id}-${l.color.name}`} className="flex gap-4 py-4">
              <Link href={`/products/${l.product.id}`} className="shrink-0">
                <ProductArt kind={l.product.art} color={l.color.hex} label={l.product.name} className="h-28 w-28 rounded-md" />
              </Link>
              <div className="flex-1">
                <Link href={`/products/${l.product.id}`} className="font-medium hover:text-indigo-700">{l.product.name}</Link>
                <p className="text-sm text-emerald-700 dark:text-emerald-400">{l.product.stock > 0 ? "In stock" : "Unavailable"}</p>
                <p className="text-sm">Colour: {l.color.name}</p>
                <div className="mt-2 flex items-center gap-3 text-sm">
                  <label>Qty{" "}
                    <select value={l.qty} onChange={(e) => setQty(l, Number(e.target.value))} className="ml-1 rounded border border-zinc-300 bg-white px-2 py-1 dark:bg-zinc-800">
                      {Array.from({ length: 10 }, (_, i) => i + 1).map((n) => <option key={n} value={n}>{n}</option>)}
                    </select>
                  </label>
                  <button type="button" onClick={() => setQty(l, 0)} className="text-sky-700 hover:underline">Delete</button>
                </div>
              </div>
              <p className="font-semibold">{formatPrice(l.lineCents)}</p>
            </li>
          ))}
        </ul>
        <p className="text-right text-lg">Subtotal ({cart.count} items): <span className="font-semibold">{formatPrice(cart.totalCents)}</span></p>
      </section>
      <aside className="h-fit rounded-lg bg-white p-5 dark:bg-zinc-900">
        <p className="text-sm text-emerald-700 dark:text-emerald-400">Your order qualifies for FREE delivery.</p>
        <p className="mt-2 text-lg">Subtotal ({cart.count} items): <span className="font-semibold">{formatPrice(cart.totalCents)}</span></p>
        <Link href="/checkout" className="mt-3 block rounded-full bg-amber-400 py-2 text-center font-semibold text-zinc-900 hover:bg-amber-300">Proceed to checkout</Link>
      </aside>
    </div>
  );
}
