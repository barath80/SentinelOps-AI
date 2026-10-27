import Link from "next/link";
import { Suspense } from "react";
import SearchBar, { SearchForm } from "./SearchBar";
import SignOutButton from "./SignOutButton";
import { detail, readCart } from "@/lib/cart";
import { CATEGORIES } from "@/lib/products";
import { getSession } from "@/lib/session";

async function AccountAndCart() {
  const [session, cart] = await Promise.all([getSession(), readCart()]);
  const count = detail(cart).count;
  return (
    <div className="flex items-center gap-4">
      {session ? (
        <details className="relative">
          <summary className="cursor-pointer list-none leading-tight">
            <span className="block text-xs text-zinc-300">Hello, {session.name.split(" ")[0]}</span>
            <span className="text-sm font-semibold">Account &amp; Orders ▾</span>
          </summary>
          <div className="absolute right-0 z-20 mt-2 flex w-44 flex-col gap-2 rounded-md bg-white p-3 text-zinc-900 shadow-lg">
            <Link href="/orders" className="text-sm hover:underline">Your orders</Link>
            <SignOutButton />
          </div>
        </details>
      ) : (
        <Link href="/login" className="leading-tight">
          <span className="block text-xs text-zinc-300">Hello, sign in</span>
          <span className="text-sm font-semibold">Account &amp; Orders</span>
        </Link>
      )}
      <Link href="/orders" className="hidden leading-tight md:block">
        <span className="block text-xs text-zinc-300">Returns</span>
        <span className="text-sm font-semibold">&amp; Orders</span>
      </Link>
      <Link href="/cart" className="relative flex items-end gap-1" aria-label={`Cart, ${count} items`}>
        <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="M3 4h2l2.4 11.2a2 2 0 0 0 2 1.6h7.7a2 2 0 0 0 2-1.5L21 8H6" /><circle cx="10" cy="20" r="1.4" /><circle cx="17" cy="20" r="1.4" /></svg>
        <span className="absolute -top-1 left-3 rounded-full bg-amber-400 px-1.5 text-xs font-bold text-zinc-900">{count}</span>
        <span className="hidden text-sm font-semibold sm:inline">Cart</span>
      </Link>
    </div>
  );
}

export default function Header() {
  return (
    <header className="bg-indigo-950 text-white">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-4 px-4 py-3">
        <Link href="/" className="text-2xl font-extrabold tracking-tight">
          Shop<span className="text-amber-400">Sphere</span>
        </Link>
        <div className="order-3 w-full md:order-none md:flex-1">
          <Suspense fallback={<SearchForm />}>
            <SearchBar />
          </Suspense>
        </div>
        <div className="ml-auto">
          <Suspense fallback={<Link href="/login" className="text-sm font-semibold">Sign in</Link>}>
            <AccountAndCart />
          </Suspense>
        </div>
      </div>
      <nav className="bg-indigo-900" aria-label="Categories">
        <div className="mx-auto flex max-w-7xl gap-4 overflow-x-auto px-4 py-2 text-sm">
          <Link href="/search?sort=bestsellers" className="whitespace-nowrap hover:underline">Best Sellers</Link>
          <Link href="/deals" className="whitespace-nowrap font-semibold text-amber-300 hover:underline">Today&apos;s Deals</Link>
          {CATEGORIES.map((c) => (
            <Link key={c.id} href={`/search?category=${c.id}`} className="whitespace-nowrap hover:underline">{c.name}</Link>
          ))}
        </div>
      </nav>
      <p className="bg-amber-100 px-4 py-1 text-center text-xs text-amber-900">
        Demo store for SentinelOps AI: brands are fictional and no real payments are taken.
      </p>
    </header>
  );
}
