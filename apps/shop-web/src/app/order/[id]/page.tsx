import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { cache } from "react";
import OrderLines from "@/components/OrderLines";
import { getOrder } from "@/lib/orders";
import { formatPrice } from "@/lib/products";
import { getSession } from "@/lib/session";

// Deduped per request: generateMetadata and the page body both need these, and this way the DB
// is only hit once.
const loadOrder = cache(getOrder);
const loadSession = cache(getSession);

// Deliberately no loading.tsx for this route: any Suspense boundary around it (explicit, or
// implicit via loading.tsx) makes Next flush a 200 shell before notFound() resolves, so an
// unknown or inaccessible order id could never actually produce a real 404. generateMetadata
// always resolves before streaming starts, so the existence/ownership check belongs here too.
export async function generateMetadata({ params }: PageProps<"/order/[id]">): Promise<Metadata> {
  const { id } = await params;
  const [order, session] = await Promise.all([loadOrder(id), loadSession()]);
  if (!order || (order.userId && order.userId !== session?.userId)) notFound();
  return { title: `Order ${order.id}` };
}

export default async function OrderPage({ params }: PageProps<"/order/[id]">) {
  const { id } = await params;
  const [order, session] = await Promise.all([loadOrder(id), loadSession()]);
  // Another customer's order looks exactly like a missing one.
  if (!order || (order.userId && order.userId !== session?.userId)) notFound();
  const own = !!order.userId && order.userId === session?.userId;
  return (
    <div className="mx-auto max-w-3xl rounded-lg bg-white p-6 dark:bg-zinc-900">
      <p className="text-lg font-semibold text-emerald-700 dark:text-emerald-400">✓ Order placed, thank you!</p>
      <h1 className="mt-1 text-2xl font-bold">Order {order.id}</h1>
      <p className="text-sm text-zinc-500">Placed {new Date(order.createdAt).toLocaleString("en-US")}. Simulated order: no payment was taken.</p>
      {own && order.shipping && (
        <div className="mt-4 text-sm">
          <p className="font-semibold">Delivering to</p>
          <p>{order.shipping.fullName}, {order.shipping.line1}, {order.shipping.city} {order.shipping.postalCode}, {order.shipping.country}</p>
        </div>
      )}
      <div className="mt-4"><OrderLines lines={order.lines} /></div>
      <p className="mt-3 text-right text-lg">Order total: <span className="font-semibold">{formatPrice(order.totalCents)}</span></p>
      <div className="mt-4 flex gap-4 text-sm">
        {own && <Link href="/orders" className="text-sky-700 hover:underline">Your orders</Link>}
        <Link href="/" className="text-sky-700 hover:underline">Continue shopping</Link>
      </div>
    </div>
  );
}
