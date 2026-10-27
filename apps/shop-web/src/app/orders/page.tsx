import Link from "next/link";
import { redirect } from "next/navigation";
import { Suspense } from "react";
import OrderLines from "@/components/OrderLines";
import { listOrders } from "@/lib/orders";
import { formatPrice } from "@/lib/products";
import { getSession } from "@/lib/session";

async function Orders() {
  const session = await getSession();
  if (!session) redirect("/login?next=/orders");
  const orders = await listOrders(session.userId);
  return (
    <>
      <h1 className="text-2xl font-bold">Your orders</h1>
      <p className="text-sm text-zinc-500">{orders.length} order{orders.length === 1 ? "" : "s"} placed</p>
      {orders.length === 0 && (
        <p className="mt-4 rounded-lg bg-white p-6 dark:bg-zinc-900">No orders yet. <Link href="/" className="text-sky-700 hover:underline">Start shopping</Link></p>
      )}
      <ul className="mt-4 space-y-4">
        {orders.map((o) => (
          <li key={o.id} className="overflow-hidden rounded-lg border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
            <div className="flex flex-wrap gap-6 bg-zinc-50 px-4 py-2 text-xs text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
              <div><p className="uppercase">Order placed</p><p className="text-sm">{new Date(o.createdAt).toLocaleDateString("en-US", { dateStyle: "medium" })}</p></div>
              <div><p className="uppercase">Total</p><p className="text-sm">{formatPrice(o.totalCents)}</p></div>
              {o.shipping && <div><p className="uppercase">Ship to</p><p className="text-sm">{o.shipping.fullName}</p></div>}
              <div className="ml-auto text-right"><p className="uppercase">Order # {o.id}</p><Link href={`/order/${o.id}`} className="text-sm text-sky-700 hover:underline">View order details</Link></div>
            </div>
            <div className="px-4 py-2">
              <p className="font-semibold capitalize text-emerald-700 dark:text-emerald-400">{o.status === "placed" ? "Order placed: arriving in 2 days" : o.status}</p>
              <OrderLines lines={o.lines} />
            </div>
          </li>
        ))}
      </ul>
    </>
  );
}

export default function OrdersPage() {
  return (
    <Suspense fallback={<p>Loading your orders…</p>}>
      <Orders />
    </Suspense>
  );
}
