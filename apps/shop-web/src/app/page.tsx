import Link from "next/link";
import ProductArt from "@/components/ProductArt";
import ProductCard from "@/components/ProductCard";
import { CATEGORIES, discountPct, PRODUCTS } from "@/lib/products";

function Row({ title, href, products }: { title: string; href: string; products: typeof PRODUCTS }) {
  return (
    <section className="mt-8">
      <div className="mb-3 flex items-baseline justify-between">
        <h2 className="text-xl font-bold">{title}</h2>
        <Link href={href} className="text-sm text-sky-700 hover:underline dark:text-sky-400">See all</Link>
      </div>
      <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6">
        {products.map((p) => <ProductCard key={p.id} p={p} />)}
      </ul>
    </section>
  );
}

export default function Home() {
  const deals = [...PRODUCTS].sort((a, b) => discountPct(b) - discountPct(a)).slice(0, 6);
  const best = [...PRODUCTS].sort((a, b) => b.boughtLastMonth - a.boughtLastMonth).slice(0, 6);
  const top = [...PRODUCTS].filter((p) => p.reviewCount > 500).sort((a, b) => b.rating - a.rating).slice(0, 6);
  const heroItems = [PRODUCTS[0], PRODUCTS[12], PRODUCTS[33]];

  return (
    <>
      <section className="relative overflow-hidden rounded-xl bg-gradient-to-r from-indigo-700 via-violet-600 to-fuchsia-500 p-8 text-white">
        <div className="max-w-xl">
          <p className="text-sm font-semibold uppercase tracking-widest text-amber-200">Autumn sale</p>
          <h1 className="mt-2 text-4xl font-extrabold leading-tight">Up to 40% off audio, fashion and home</h1>
          <p className="mt-3 text-indigo-100">Free 2-day delivery on thousands of items. New deals every day.</p>
          <div className="mt-5 flex gap-3">
            <Link href="/deals" className="rounded-md bg-amber-400 px-5 py-2.5 font-semibold text-zinc-900 hover:bg-amber-300">Shop today&apos;s deals</Link>
            <Link href="/search?sort=bestsellers" className="rounded-md bg-white/15 px-5 py-2.5 font-semibold hover:bg-white/25">Best sellers</Link>
          </div>
        </div>
        <div className="pointer-events-none absolute -right-6 bottom-0 hidden gap-3 lg:flex">
          {heroItems.map((p, i) => (
            <ProductArt key={p.id} kind={p.art} color={p.colors[i % p.colors.length].hex} label={p.name} className="h-40 w-40 rounded-xl shadow-xl" />
          ))}
        </div>
      </section>

      <section className="mt-8 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {CATEGORIES.map((c) => {
          const p = PRODUCTS.find((x) => x.category === c.id)!;
          return (
            <Link key={c.id} href={`/search?category=${c.id}`} className="group rounded-lg bg-white p-3 hover:shadow-md dark:bg-zinc-900">
              <ProductArt kind={p.art} color={p.colors[1]?.hex ?? p.colors[0].hex} label={c.name} className="aspect-[4/3] w-full rounded-md" />
              <p className="mt-2 font-semibold group-hover:text-indigo-700 dark:group-hover:text-indigo-300">{c.name}</p>
              <p className="text-xs text-zinc-500">{c.blurb}</p>
            </Link>
          );
        })}
      </section>

      <Row title="Today's deals" href="/deals" products={deals} />
      <Row title="Best sellers" href="/search?sort=bestsellers" products={best} />
      <Row title="Top rated by customers" href="/search?sort=rating" products={top} />
    </>
  );
}
