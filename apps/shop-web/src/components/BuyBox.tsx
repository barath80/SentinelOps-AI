"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import ProductArt from "./ProductArt";
import Stars from "./Stars";
import { discountPct, formatCount, formatPrice, type Product } from "@/lib/products";

export default function BuyBox({ p }: { p: Product }) {
  const router = useRouter();
  const [color, setColor] = useState(p.colors[0]);
  const [qty, setQty] = useState(1);
  const [state, setState] = useState<"idle" | "busy" | "added" | "error">("idle");
  const [message, setMessage] = useState("");
  const off = discountPct(p);

  async function add(thenGo?: string) {
    setState("busy");
    const res = await fetch("/api/cart", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ id: p.id, qty, color: color.name, add: true }),
    }).catch(() => null);
    if (!res || !res.ok) {
      const body = res ? await res.json().catch(() => ({})) : {};
      setState("error");
      setMessage(body.error === "invalid_quantity" ? `You can have at most ${body.max} of one item in your cart.` : "Could not add to cart. Try again.");
      return;
    }
    setState("added");
    router.refresh(); // update the cart count in the header
    if (thenGo) router.push(thenGo);
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[1.1fr_1fr_300px]">
      <div className="rounded-lg bg-white p-4 dark:bg-zinc-900">
        <ProductArt kind={p.art} color={color.hex} label={`${p.name} in ${color.name}`} className="aspect-square w-full rounded-md" />
        <div className="mt-3 flex gap-2">
          {p.colors.map((c) => (
            <button key={c.name} type="button" onClick={() => setColor(c)} aria-label={`Show ${c.name}`}
              className={`overflow-hidden rounded-md border-2 ${c.name === color.name ? "border-indigo-600" : "border-transparent"}`}>
              <ProductArt kind={p.art} color={c.hex} label="" className="h-14 w-14" />
            </button>
          ))}
        </div>
      </div>

      <div>
        <Link href={`/search?brand=${encodeURIComponent(p.brand)}`} className="text-sm text-sky-700 hover:underline dark:text-sky-400">Visit the {p.brand} store</Link>
        <h1 className="mt-1 text-2xl font-semibold leading-snug">{p.name}</h1>
        <div className="mt-1 flex flex-wrap items-center gap-3">
          <Stars rating={p.rating} count={p.reviewCount} />
          {p.badge && <span className="rounded bg-orange-600 px-2 py-0.5 text-xs font-semibold text-white">{p.badge}</span>}
        </div>
        {p.boughtLastMonth >= 50 && <p className="text-sm text-zinc-500">{formatCount(p.boughtLastMonth)}+ bought in past month</p>}
        <hr className="my-3 border-zinc-200 dark:border-zinc-800" />
        <div className="flex items-baseline gap-3">
          {off > 0 && <span className="text-2xl font-light text-red-600">-{off}%</span>}
          <span className="text-3xl font-semibold">{formatPrice(p.priceCents)}</span>
        </div>
        {off > 0 && <p className="text-sm text-zinc-500">List price: <s>{formatPrice(p.listPriceCents)}</s></p>}
        <p className="mt-4 text-sm">Colour: <span className="font-semibold">{color.name}</span></p>
        <div className="mt-2 flex flex-wrap gap-2">
          {p.colors.map((c) => (
            <button key={c.name} type="button" onClick={() => setColor(c)} title={c.name} aria-label={c.name} aria-pressed={c.name === color.name}
              className={`h-8 w-8 rounded-full border-2 ${c.name === color.name ? "border-indigo-600 ring-2 ring-indigo-200" : "border-zinc-300"}`} style={{ background: c.hex }} />
          ))}
        </div>
        <p className="mt-4 text-sm leading-relaxed text-zinc-700 dark:text-zinc-300">{p.description}</p>
      </div>

      <aside className="h-fit rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
        <p className="text-2xl font-semibold">{formatPrice(p.priceCents)}</p>
        {p.fastDelivery ? <p className="mt-1 text-sm text-emerald-700 dark:text-emerald-400">FREE 2-day delivery</p> : <p className="mt-1 text-sm">Delivery in 4-6 days</p>}
        <p className={`mt-2 font-semibold ${p.stock === 0 ? "text-red-600" : p.stock < 10 ? "text-orange-600" : "text-emerald-700 dark:text-emerald-400"}`}>
          {p.stock === 0 ? "Currently unavailable" : p.stock < 10 ? `Only ${p.stock} left in stock` : "In stock"}
        </p>
        {p.stock > 0 && (
          <>
            <label className="mt-3 block text-sm">Quantity{" "}
              <select value={qty} onChange={(e) => setQty(Number(e.target.value))} className="ml-1 rounded border border-zinc-300 bg-white px-2 py-1 dark:bg-zinc-800">
                {Array.from({ length: Math.min(10, p.stock) }, (_, i) => i + 1).map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
            </label>
            <button type="button" disabled={state === "busy"} onClick={() => add()}
              className="mt-3 w-full rounded-full bg-amber-400 py-2 font-semibold text-zinc-900 hover:bg-amber-300 disabled:opacity-60">
              {state === "added" ? "Added to cart ✓" : "Add to cart"}
            </button>
            <button type="button" disabled={state === "busy"} onClick={() => add("/checkout")}
              className="mt-2 w-full rounded-full bg-orange-500 py-2 font-semibold text-white hover:bg-orange-400 disabled:opacity-60">
              Buy now
            </button>
          </>
        )}
        {state === "error" && <p role="alert" className="mt-2 text-sm text-red-600">{message}</p>}
        {state === "added" && <Link href="/cart" className="mt-2 block text-center text-sm text-sky-700 hover:underline">Go to cart</Link>}
        <p className="mt-3 text-xs text-zinc-500">Ships from and sold by ShopSphere. Simulated checkout: no payment is taken.</p>
      </aside>
    </div>
  );
}
