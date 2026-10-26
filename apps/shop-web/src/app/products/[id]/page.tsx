import { notFound } from "next/navigation";
import { Suspense } from "react";
import AddToCart from "@/components/AddToCart";
import { formatPrice, getProduct } from "@/lib/products";

export default function ProductPage({ params }: PageProps<"/products/[id]">) {
  return (
    <Suspense fallback={<p>Loading…</p>}>
      <Product params={params} />
    </Suspense>
  );
}

async function Product({ params }: Pick<PageProps<"/products/[id]">, "params">) {
  const { id } = await params;
  const p = getProduct(id);
  if (!p) notFound();
  return (
    <article className="space-y-3">
      <h1 className="text-2xl font-semibold">{p.name}</h1>
      <p className="text-zinc-500">{p.category}</p>
      <p>{p.description}</p>
      <p className="text-xl">{formatPrice(p.priceCents)}</p>
      <p className="text-sm">{p.stock} in stock</p>
      <AddToCart productId={p.id} />
    </article>
  );
}
