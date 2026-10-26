import Link from "next/link";
import { Suspense } from "react";
import AddToCart from "@/components/AddToCart";
import { formatPrice, listProducts } from "@/lib/products";

export default function Home({ searchParams }: PageProps<"/">) {
  return (
    <Suspense fallback={<p>Loading products…</p>}>
      <Catalogue searchParams={searchParams} />
    </Suspense>
  );
}

async function Catalogue({ searchParams }: Pick<PageProps<"/">, "searchParams">) {
  const sp = await searchParams;
  const q = typeof sp.q === "string" ? sp.q : undefined;
  const products = listProducts(q);

  return (
    <>
      <form className="mb-6 flex gap-2" action="/">
        <input name="q" defaultValue={q} placeholder="Search products" className="flex-1 rounded border px-3 py-2" />
        <button className="rounded border px-3 py-2">Search</button>
      </form>
      {products.length === 0 && <p>No products match.</p>}
      <ul className="grid gap-4 sm:grid-cols-2">
        {products.map((p) => (
          <li key={p.id} className="rounded border p-4">
            <Link href={`/products/${p.id}`} className="font-medium underline">{p.name}</Link>
            <p className="text-sm text-zinc-500">{p.category}</p>
            <p className="my-2">{formatPrice(p.priceCents)}</p>
            <AddToCart productId={p.id} />
          </li>
        ))}
      </ul>
    </>
  );
}
