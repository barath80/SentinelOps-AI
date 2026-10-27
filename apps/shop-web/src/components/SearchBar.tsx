"use client";
import { useSearchParams } from "next/navigation";
import { CATEGORIES } from "@/lib/products";

export default function SearchBar() {
  const sp = useSearchParams();
  return <SearchForm q={sp.get("q") ?? ""} category={sp.get("category") ?? ""} />;
}

export function SearchForm({ q = "", category = "" }: { q?: string; category?: string }) {
  return (
    <form action="/search" role="search" className="flex w-full overflow-hidden rounded-md bg-white ring-2 ring-transparent focus-within:ring-amber-400">
      <label className="sr-only" htmlFor="search-category">Category</label>
      <select id="search-category" name="category" defaultValue={category} className="hidden border-r border-zinc-300 bg-zinc-100 px-2 text-sm text-zinc-800 sm:block">
        <option value="">All</option>
        {CATEGORIES.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
      </select>
      <label className="sr-only" htmlFor="search-q">Search ShopSphere</label>
      <input id="search-q" name="q" defaultValue={q} placeholder="Search products, brands and colours" className="min-w-0 flex-1 px-3 py-2 text-zinc-900 outline-none" />
      <button className="bg-amber-400 px-4 text-zinc-900 hover:bg-amber-300" aria-label="Search">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="m20 20-4-4" /></svg>
      </button>
    </form>
  );
}
