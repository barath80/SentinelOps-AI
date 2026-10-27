import Link from "next/link";
import ProductArt from "./ProductArt";
import { formatPrice, getProduct, type ArtKind } from "@/lib/products";
import type { OrderLine } from "@/lib/orders";

export default function OrderLines({ lines }: { lines: OrderLine[] }) {
  return (
    <ul className="divide-y divide-zinc-200 dark:divide-zinc-800">
      {lines.map((l, i) => {
        const p = getProduct(l.id);
        const art = (l.art ?? p?.art ?? "blocks") as ArtKind;
        const hex = l.colorHex ?? p?.colors[0].hex ?? "#64748b";
        return (
          <li key={`${l.id}-${l.color}-${i}`} className="flex items-center gap-3 py-2">
            <ProductArt kind={art} color={hex} label={l.name} className="h-16 w-16 rounded" />
            <div className="flex-1 text-sm">
              {p ? <Link href={`/products/${p.id}`} className="font-medium hover:text-indigo-700">{l.name}</Link> : <span className="font-medium">{l.name}</span>}
              <p className="text-zinc-500">{l.color ? `${l.color} · ` : ""}Qty {l.qty}</p>
            </div>
            <span className="text-sm font-semibold">{formatPrice(l.lineCents)}</span>
          </li>
        );
      })}
    </ul>
  );
}
