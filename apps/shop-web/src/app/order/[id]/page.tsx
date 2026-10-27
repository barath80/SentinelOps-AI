import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import OrderLines from "@/components/OrderLines";
import { getOrder } from "@/lib/orders";
import { formatPrice } from "@/lib/products";
import { getSession } from "@/lib/session";

async function Order({ params }: Pick<PageProps<"/order/[id]">, "params">) {
  const { id } = await params;
  const [order, session] = await Promise.all([getOrder(id), getSession()]);
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

export default function OrderPage({ params }: PageProps<"/order/[id]">) {
  return (
    <Suspense fallback={<p>Loading…</p>}>
      <Order params={params} />
    </Suspense>
  );
}
