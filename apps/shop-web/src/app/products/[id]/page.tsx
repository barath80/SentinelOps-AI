import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import BuyBox from "@/components/BuyBox";
import ProductCard from "@/components/ProductCard";
import Stars from "@/components/Stars";
import { CATEGORIES, formatCount, getProduct, PRODUCTS, type Product } from "@/lib/products";
import { buildBreadcrumbJsonLd, buildProductJsonLd, productMetaDescription, siteUrl } from "@/lib/seo";

// Share of reviews per star level, derived from the average so the bars agree with the rating.
function distribution(p: Product): number[] {
  const weights = [5, 4, 3, 2, 1].map((s) => Math.exp(-Math.abs(s - p.rating) * 1.6));
  const total = weights.reduce((a, b) => a + b, 0);
  return weights.map((w) => Math.round((w / total) * 100));
}

// Deliberately no loading.tsx for this route: any Suspense boundary around it (explicit, or
// implicit via loading.tsx) makes Next flush a 200 shell before notFound() resolves, so an
// unknown id could never actually produce a real 404. generateMetadata always resolves before
// streaming starts, so the existence check belongs here too.
export async function generateMetadata({ params }: PageProps<"/products/[id]">): Promise<Metadata> {
  const { id } = await params;
  const p = getProduct(id);
  if (!p) notFound();
  const description = productMetaDescription(p);
  return {
    title: p.name,
    description,
    alternates: { canonical: `/products/${p.id}` },
    openGraph: { title: p.name, description, type: "website", images: [`/products/${p.id}/opengraph-image`] },
  };
}

export default async function ProductPage({ params }: PageProps<"/products/[id]">) {
  const { id } = await params;
  const p = getProduct(id);
  if (!p) notFound();
  const category = CATEGORIES.find((c) => c.id === p.category)!;
  const related = PRODUCTS.filter((x) => x.category === p.category && x.id !== p.id).slice(0, 6);
  const dist = distribution(p);
  const base = siteUrl();
  const productUrl = `${base}/products/${p.id}`;
  const breadcrumbJsonLd = buildBreadcrumbJsonLd([
    { name: "Home", url: base },
    { name: category.name, url: `${base}/search?category=${category.id}` },
    { name: p.name, url: productUrl },
  ]);

  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(buildProductJsonLd(p, productUrl)) }} />
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(breadcrumbJsonLd) }} />
      <nav className="mb-3 text-sm text-zinc-500" aria-label="Breadcrumb">
        <Link href="/" className="hover:underline">Home</Link> ›{" "}
        <Link href={`/search?category=${category.id}`} className="hover:underline">{category.name}</Link> ›{" "}
        <span>{p.brand}</span>
      </nav>
      <BuyBox p={p} />

      <section className="mt-8 grid gap-6 lg:grid-cols-2">
        <div className="rounded-lg bg-white p-5 dark:bg-zinc-900">
          <h2 className="text-lg font-bold">About this item</h2>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm">
            {p.bullets.map((b) => <li key={b}>{b}</li>)}
          </ul>
          <h2 className="mt-5 text-lg font-bold">Product details</h2>
          <table className="mt-2 w-full text-sm">
            <tbody>
              {Object.entries(p.specs).map(([k, v]) => (
                <tr key={k} className="border-b border-zinc-100 dark:border-zinc-800">
                  <th className="w-40 py-1.5 pr-3 text-left font-medium text-zinc-500">{k}</th>
                  <td className="py-1.5">{v}</td>
                </tr>
              ))}
              <tr><th className="py-1.5 pr-3 text-left font-medium text-zinc-500">Colours</th><td>{p.colors.map((c) => c.name).join(", ")}</td></tr>
              <tr><th className="py-1.5 pr-3 text-left font-medium text-zinc-500">Item code</th><td>{p.id.toUpperCase()}</td></tr>
            </tbody>
          </table>
        </div>
        <div className="rounded-lg bg-white p-5 dark:bg-zinc-900">
          <h2 className="text-lg font-bold">Customer reviews</h2>
          <div className="mt-1"><Stars rating={p.rating} size={20} /></div>
          <p className="text-sm text-zinc-500">{formatCount(p.reviewCount)} global ratings</p>
          <ul className="mt-3 space-y-1.5">
            {dist.map((pct, i) => (
              <li key={i} className="flex items-center gap-2 text-sm">
                <span className="w-12 text-sky-700 dark:text-sky-400">{5 - i} star</span>
                <span className="h-4 flex-1 overflow-hidden rounded bg-zinc-200 dark:bg-zinc-800"><span className="block h-full bg-amber-400" style={{ width: `${pct}%` }} /></span>
                <span className="w-10 text-right text-zinc-500">{pct}%</span>
              </li>
            ))}
          </ul>
          <p className="mt-3 text-xs text-zinc-500">Ratings in this demo store are generated, not written by real customers.</p>
        </div>
      </section>

      <section className="mt-8">
        <h2 className="mb-3 text-xl font-bold">Customers also viewed</h2>
        <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          {related.map((x) => <ProductCard key={x.id} p={x} />)}
        </ul>
      </section>
    </>
  );
}
