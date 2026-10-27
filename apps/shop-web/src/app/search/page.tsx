import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";
import EmptyState from "@/components/EmptyState";
import ProductCard from "@/components/ProductCard";
import { CATEGORIES, searchProducts, type SortKey } from "@/lib/products";

const SORTS: { key: SortKey; label: string }[] = [
  { key: "relevance", label: "Featured" },
  { key: "price-asc", label: "Price: low to high" },
  { key: "price-desc", label: "Price: high to low" },
  { key: "rating", label: "Avg. customer review" },
  { key: "reviews", label: "Most reviewed" },
  { key: "bestsellers", label: "Best sellers" },
];
const PRICES: { label: string; min?: number; max?: number }[] = [
  { label: "Under $25", max: 25 }, { label: "$25 to $50", min: 25, max: 50 }, { label: "$50 to $100", min: 50, max: 100 },
  { label: "$100 to $200", min: 100, max: 200 }, { label: "$200 & above", min: 200 },
];
const PAGE_SIZE = 24;
type Params = Record<string, string | undefined>;

function href(current: Params, change: Params): string {
  const next = { ...current, ...change, page: change.page ?? undefined };
  const qs = new URLSearchParams(Object.entries(next).filter(([, v]) => v !== undefined && v !== "") as [string, string][]);
  return `/search${qs.size ? `?${qs}` : ""}`;
}

function FilterLink({ active, to, children }: { active: boolean; to: string; children: React.ReactNode }) {
  return <li><Link href={to} className={active ? "font-semibold text-indigo-700 dark:text-indigo-300" : "hover:text-indigo-700 dark:hover:text-indigo-300"}>{children}</Link></li>;
}

async function Results({ searchParams }: Pick<PageProps<"/search">, "searchParams">) {
  const raw = await searchParams;
  const p: Params = Object.fromEntries(Object.entries(raw).map(([k, v]) => [k, typeof v === "string" ? v : undefined]));
  const num = (v?: string) => (v && Number.isFinite(Number(v)) ? Number(v) : undefined);
  const sort = (SORTS.find((s) => s.key === p.sort)?.key ?? "relevance") as SortKey;
  const base = searchProducts({ q: p.q, category: p.category, sort });
  const results = searchProducts({
    q: p.q, category: p.category, brand: p.brand, sort,
    minCents: num(p.min) !== undefined ? num(p.min)! * 100 : undefined,
    maxCents: num(p.max) !== undefined ? num(p.max)! * 100 : undefined,
    minRating: num(p.rating),
  });
  const brands = [...new Set(base.map((x) => x.brand))].sort();
  const page = Math.max(1, Math.floor(num(p.page) ?? 1));
  const pages = Math.max(1, Math.ceil(results.length / PAGE_SIZE));
  const shown = results.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
  const category = CATEGORIES.find((c) => c.id === p.category);

  return (
    <div className="grid gap-6 md:grid-cols-[220px_1fr]">
      <aside className="space-y-5 text-sm" aria-label="Filters">
        <div>
          <p className="font-semibold">Department</p>
          <ul className="mt-1 space-y-1">
            <FilterLink active={!p.category} to={href(p, { category: undefined, brand: undefined })}>All departments</FilterLink>
            {CATEGORIES.map((c) => <FilterLink key={c.id} active={p.category === c.id} to={href(p, { category: c.id, brand: undefined })}>{c.name}</FilterLink>)}
          </ul>
        </div>
        <div>
          <p className="font-semibold">Customer reviews</p>
          <ul className="mt-1 space-y-1">
            {[4, 3].map((r) => <FilterLink key={r} active={p.rating === String(r)} to={href(p, { rating: p.rating === String(r) ? undefined : String(r) })}>{"★".repeat(r)}{"☆".repeat(5 - r)} &amp; up</FilterLink>)}
          </ul>
        </div>
        <div>
          <p className="font-semibold">Price</p>
          <ul className="mt-1 space-y-1">
            {PRICES.map((pr) => {
              const active = p.min === (pr.min?.toString() ?? undefined) && p.max === (pr.max?.toString() ?? undefined);
              return <FilterLink key={pr.label} active={active} to={href(p, active ? { min: undefined, max: undefined } : { min: pr.min?.toString(), max: pr.max?.toString() })}>{pr.label}</FilterLink>;
            })}
          </ul>
        </div>
        <div>
          <p className="font-semibold">Brands</p>
          <ul className="mt-1 space-y-1">
            {brands.map((b) => <FilterLink key={b} active={p.brand === b} to={href(p, { brand: p.brand === b ? undefined : b })}>{b}</FilterLink>)}
          </ul>
        </div>
      </aside>

      <section>
        <div className="flex flex-wrap items-baseline justify-between gap-2 rounded-md bg-white px-3 py-2 text-sm shadow-sm dark:bg-zinc-900">
          <p>
            {results.length === 0 ? "No results" : `${(page - 1) * PAGE_SIZE + 1}-${Math.min(page * PAGE_SIZE, results.length)} of ${results.length} results`}
            {p.q && <> for <span className="font-semibold text-orange-700">&quot;{p.q}&quot;</span></>}
            {category && <> in <span className="font-semibold">{category.name}</span></>}
          </p>
          <div className="flex flex-wrap gap-2">
            <span className="text-zinc-500">Sort by:</span>
            {SORTS.map((s) => <Link key={s.key} href={href(p, { sort: s.key })} className={s.key === sort ? "font-semibold text-indigo-700 dark:text-indigo-300" : "hover:underline"}>{s.label}</Link>)}
          </div>
        </div>
        {shown.length === 0 ? (
          <div className="mt-6">
            <EmptyState
              title="No products match these filters"
              message="Try removing a filter or searching for something else."
              action={{ href: "/search", label: "Clear all filters" }}
            />
          </div>
        ) : (
          <ul className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-4">
            {shown.map((x) => <ProductCard key={x.id} p={x} />)}
          </ul>
        )}
        {pages > 1 && (
          <nav className="mt-6 flex justify-center gap-2" aria-label="Pages">
            {Array.from({ length: pages }, (_, i) => i + 1).map((n) => (
              <Link key={n} href={href(p, { page: String(n) })} aria-current={n === page ? "page" : undefined}
                className={`rounded border px-3 py-1 ${n === page ? "border-indigo-600 bg-indigo-600 text-white" : "border-zinc-300 bg-white dark:bg-zinc-900"}`}>{n}</Link>
            ))}
          </nav>
        )}
      </section>
    </div>
  );
}

export async function generateMetadata({ searchParams }: PageProps<"/search">): Promise<Metadata> {
  const sp = await searchParams;
  const q = typeof sp.q === "string" ? sp.q : undefined;
  const category = typeof sp.category === "string" ? CATEGORIES.find((c) => c.id === sp.category)?.name : undefined;
  // Only the bare landing view and bare category views are worth indexing; a text query or any
  // price/rating/brand/page filter would otherwise create endless near-duplicate pages.
  const hasNarrowingFilter = ["q", "min", "max", "rating", "brand", "page"].some((k) => sp[k]);
  const title = q ? `"${q}" search results` : category ? `${category} — Shop ${category}` : "Search";
  return {
    title,
    alternates: { canonical: "/search" },
    robots: hasNarrowingFilter ? { index: false, follow: true } : undefined,
  };
}

export default function SearchPage({ searchParams }: PageProps<"/search">) {
  return (
    <Suspense fallback={<p>Loading results…</p>}>
      <Results searchParams={searchParams} />
    </Suspense>
  );
}
