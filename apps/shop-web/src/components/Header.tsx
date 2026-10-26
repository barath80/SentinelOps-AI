import Link from "next/link";

export default function Header() {
  return (
    <header className="border-b border-zinc-200 dark:border-zinc-800">
      <nav className="mx-auto flex max-w-4xl items-center justify-between px-4 py-4">
        <Link href="/" className="text-lg font-semibold">ShopSphere</Link>
        <div className="flex items-center gap-4 text-sm">
          <span className="rounded bg-amber-100 px-2 py-1 text-amber-900">Demo: no real payments</span>
          <Link href="/cart">Cart</Link>
        </div>
      </nav>
    </header>
  );
}
