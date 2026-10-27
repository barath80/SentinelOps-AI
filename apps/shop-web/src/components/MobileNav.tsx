"use client";
import * as Dialog from "@radix-ui/react-dialog";
import Link from "next/link";
import { CATEGORIES } from "@/lib/products";

export default function MobileNav() {
  return (
    <Dialog.Root>
      <Dialog.Trigger asChild>
        <button
          type="button"
          aria-label="Open menu"
          className="flex h-9 w-9 items-center justify-center rounded-md hover:bg-white/10 md:hidden"
        >
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <path d="M3 6h18M3 12h18M3 18h18" strokeLinecap="round" />
          </svg>
        </button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="ui-animate-overlay fixed inset-0 z-40 bg-black/40" />
        <Dialog.Content className="ui-animate-slide-left fixed inset-y-0 left-0 z-50 flex h-full w-72 flex-col bg-white p-4 text-zinc-900 shadow-xl outline-none dark:bg-zinc-900 dark:text-zinc-100">
          <div className="flex items-center justify-between">
            <Dialog.Title className="text-lg font-bold">Shop by department</Dialog.Title>
            <Dialog.Close asChild>
              <button type="button" aria-label="Close menu" className="rounded p-1 hover:bg-zinc-100 dark:hover:bg-zinc-800">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                  <path d="M6 6l12 12M18 6L6 18" strokeLinecap="round" />
                </svg>
              </button>
            </Dialog.Close>
          </div>
          <nav className="mt-4 flex flex-col gap-1 overflow-y-auto">
            <Dialog.Close asChild>
              <Link href="/search?sort=bestsellers" className="rounded px-2 py-2 text-sm font-medium hover:bg-zinc-100 dark:hover:bg-zinc-800">
                Best Sellers
              </Link>
            </Dialog.Close>
            <Dialog.Close asChild>
              <Link href="/deals" className="rounded px-2 py-2 text-sm font-semibold text-orange-600 hover:bg-zinc-100 dark:text-amber-400 dark:hover:bg-zinc-800">
                Today&apos;s Deals
              </Link>
            </Dialog.Close>
            <hr className="my-2 border-zinc-200 dark:border-zinc-800" />
            {CATEGORIES.map((c) => (
              <Dialog.Close asChild key={c.id}>
                <Link href={`/search?category=${c.id}`} className="rounded px-2 py-2 text-sm hover:bg-zinc-100 dark:hover:bg-zinc-800">
                  {c.name}
                </Link>
              </Dialog.Close>
            ))}
          </nav>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
