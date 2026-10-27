import Link from "next/link";
import { Suspense } from "react";
import AccountMenu from "./AccountMenu";
import CartDrawer from "./CartDrawer";
import MobileNav from "./MobileNav";
import SearchBar, { SearchForm } from "./SearchBar";
import { detail, readCart } from "@/lib/cart";
import { CATEGORIES } from "@/lib/products";
import { getSession } from "@/lib/session";

async function AccountAndCart() {
  const [session, cart] = await Promise.all([getSession(), readCart()]);
  const count = detail(cart).count;
  return (
    <div className="flex items-center gap-4">
      {session ? (
        <AccountMenu name={session.name} />
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
      <CartDrawer count={count} />
    </div>
  );
}

export default function Header() {
  return (
    <header className="sticky top-0 z-30 bg-indigo-950 text-white">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-4 px-4 py-3">
        <MobileNav />
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
      <nav className="hidden bg-indigo-900 md:block" aria-label="Categories">
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
