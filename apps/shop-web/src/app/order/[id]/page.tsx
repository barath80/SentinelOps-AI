import { notFound } from "next/navigation";
import { Suspense } from "react";
import { getOrder } from "@/lib/orders";
import { formatPrice } from "@/lib/products";

export default function OrderPage({ params }: PageProps<"/order/[id]">) {
  return (
    <Suspense fallback={<p>Loading…</p>}>
      <Order params={params} />
    </Suspense>
  );
}

async function Order({ params }: Pick<PageProps<"/order/[id]">, "params">) {
  const { id } = await params;
  const order = getOrder(id);
  if (!order) notFound();
  return (
    <div className="space-y-3">
      <h1 className="text-2xl font-semibold">Order {order.id} confirmed</h1>
      <p className="text-sm text-zinc-500">Simulated order. No payment was taken.</p>
      <ul>
        {order.lines.map((l) => (
          <li key={l.id}>
            {l.name} × {l.qty} — {formatPrice(l.lineCents)}
          </li>
        ))}
      </ul>
      <p className="font-medium">Total: {formatPrice(order.totalCents)}</p>
    </div>
  );
}
