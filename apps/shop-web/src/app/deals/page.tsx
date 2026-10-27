import type { Metadata } from "next";
import ProductCard from "@/components/ProductCard";
import { discountPct, PRODUCTS } from "@/lib/products";

export const metadata: Metadata = {
  title: "Today's Deals",
  description: "Shop today's biggest discounts across electronics, fashion, home and more.",
  alternates: { canonical: "/deals" },
};

export default function Deals() {
  const deals = PRODUCTS.filter((p) => discountPct(p) > 0).sort((a, b) => discountPct(b) - discountPct(a));
  return (
    <>
      <h1 className="text-2xl font-bold">Today&apos;s deals</h1>
      <p className="text-sm text-zinc-500">{deals.length} discounted items, biggest savings first.</p>
      <ul className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6">
        {deals.map((p) => <ProductCard key={p.id} p={p} />)}
      </ul>
    </>
  );
}
