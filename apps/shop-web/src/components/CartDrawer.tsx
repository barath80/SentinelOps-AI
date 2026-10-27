"use client";
import * as Dialog from "@radix-ui/react-dialog";
import Link from "next/link";
import { useState } from "react";
import ProductArt from "./ProductArt";
import { Skeleton } from "./Skeleton";
import { formatPrice, type ArtKind } from "@/lib/products";

type Line = { product: { id: string; name: string; art: ArtKind }; color: { hex: string }; qty: number; lineCents: number };
type CartView = { lines: Line[]; totalCents: number; count: number };

export default function CartDrawer({ count }: { count: number }) {
  const [cart, setCart] = useState<CartView | null>(null);

  async function onOpenChange(open: boolean) {
    if (open && !cart) {
      const res = await fetch("/api/cart");
      if (res.ok) setCart(await res.json());
    }
  }

  return (
    <Dialog.Root onOpenChange={onOpenChange}>
      <Dialog.Trigger asChild>
        <button type="button" className="relative flex items-end gap-1 outline-none" aria-label={`Cart, ${count} items`}>
          <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
            <path d="M3 4h2l2.4 11.2a2 2 0 0 0 2 1.6h7.7a2 2 0 0 0 2-1.5L21 8H6" />
            <circle cx="10" cy="20" r="1.4" />
            <circle cx="17" cy="20" r="1.4" />
          </svg>
          <span className="absolute -top-1 left-3 rounded-full bg-amber-400 px-1.5 text-xs font-bold text-zinc-900">{count}</span>
          <span className="hidden text-sm font-semibold sm:inline">Cart</span>
        </button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="ui-animate-overlay fixed inset-0 z-40 bg-black/40" />
        <Dialog.Content className="ui-animate-slide-right fixed inset-y-0 right-0 z-50 flex h-full w-full max-w-sm flex-col bg-white p-4 text-zinc-900 shadow-xl outline-none dark:bg-zinc-900 dark:text-zinc-100">
          <div className="flex items-center justify-between">
            <Dialog.Title className="text-lg font-bold">Your cart</Dialog.Title>
            <Dialog.Close asChild>
              <button type="button" aria-label="Close cart" className="rounded p-1 hover:bg-zinc-100 dark:hover:bg-zinc-800">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                  <path d="M6 6l12 12M18 6L6 18" strokeLinecap="round" />
                </svg>
              </button>
            </Dialog.Close>
          </div>

          <div className="mt-4 flex-1 overflow-y-auto">
            {!cart ? (
              <div className="space-y-3">
                {Array.from({ length: 2 }, (_, i) => <Skeleton key={i} className="h-20 w-full" />)}
              </div>
            ) : cart.lines.length === 0 ? (
              <p className="text-sm text-zinc-500">Your cart is empty.</p>
            ) : (
              <ul className="space-y-3">
                {cart.lines.map((l) => (
                  <li key={l.product.id} className="flex gap-3">
                    <ProductArt kind={l.product.art} color={l.color.hex} label={l.product.name} className="h-16 w-16 shrink-0 rounded-md" />
                    <div className="flex-1 text-sm">
                      <p className="line-clamp-2 font-medium">{l.product.name}</p>
                      <p className="text-zinc-500">Qty {l.qty}</p>
                    </div>
                    <p className="text-sm font-semibold">{formatPrice(l.lineCents)}</p>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {cart && cart.lines.length > 0 && (
            <div className="mt-4 space-y-2 border-t border-zinc-200 pt-4 dark:border-zinc-800">
              <p className="text-right text-sm">
                Subtotal: <span className="font-semibold">{formatPrice(cart.totalCents)}</span>
              </p>
              <Dialog.Close asChild>
                <Link href="/cart" className="block rounded-full border border-zinc-300 py-2 text-center text-sm font-semibold hover:bg-zinc-50 dark:border-zinc-700 dark:hover:bg-zinc-800">
                  View cart
                </Link>
              </Dialog.Close>
              <Dialog.Close asChild>
                <Link href="/checkout" className="block rounded-full bg-amber-400 py-2 text-center text-sm font-semibold text-zinc-900 hover:bg-amber-300">
                  Checkout
                </Link>
              </Dialog.Close>
            </div>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
