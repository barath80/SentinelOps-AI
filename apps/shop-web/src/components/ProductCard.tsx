import Link from "next/link";
import ProductArt from "./ProductArt";
import Stars from "./Stars";
import { discountPct, formatCount, formatPrice, type Product } from "@/lib/products";

export default function ProductCard({ p }: { p: Product }) {
  const off = discountPct(p);
  return (
    <li className="flex flex-col rounded-lg border border-zinc-200 bg-white p-3 transition hover:shadow-md dark:border-zinc-800 dark:bg-zinc-900">
      <Link href={`/products/${p.id}`} className="relative block overflow-hidden rounded-md">
        <ProductArt kind={p.art} color={p.colors[0].hex} label={p.name} className="aspect-square w-full" />
        {p.badge && (
          <span className={`absolute left-2 top-2 rounded px-2 py-0.5 text-xs font-semibold text-white ${p.badge === "Best Seller" ? "bg-orange-600" : p.badge === "Limited deal" ? "bg-red-600" : "bg-indigo-600"}`}>
            {p.badge}
          </span>
        )}
      </Link>
      <div className="mt-2 flex gap-1" aria-label="Available colours">
        {p.colors.map((c) => (
          <span key={c.name} title={c.name} className="h-3.5 w-3.5 rounded-full border border-zinc-300" style={{ background: c.hex }} />
        ))}
      </div>
      <p className="mt-1 text-xs uppercase tracking-wide text-zinc-500">{p.brand}</p>
      <Link href={`/products/${p.id}`} className="line-clamp-2 font-medium hover:text-indigo-700 dark:hover:text-indigo-300">{p.name}</Link>
      <Stars rating={p.rating} count={p.reviewCount} />
      {p.boughtLastMonth >= 50 && <p className="text-xs text-zinc-500">{formatCount(p.boughtLastMonth)}+ bought in past month</p>}
      <div className="mt-auto pt-2">
        <span className="text-xl font-semibold">{formatPrice(p.priceCents)}</span>
        {off > 0 && (
          <span className="ml-2 text-sm text-zinc-500">
            <s>{formatPrice(p.listPriceCents)}</s> <span className="font-medium text-red-600">-{off}%</span>
          </span>
        )}
        {p.fastDelivery && <p className="text-xs text-emerald-700 dark:text-emerald-400">Free 2-day delivery</p>}
      </div>
    </li>
  );
}
