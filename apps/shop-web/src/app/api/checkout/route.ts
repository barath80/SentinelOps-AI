import { instrument } from "@/lib/handler";
import { detail, readCart, writeCart } from "@/lib/cart";
import { activeScenario, InjectedFault, sleep } from "@/lib/faults";
import { findByKey, saveOrder } from "@/lib/orders";
import { authorize, PaymentTimeout } from "@/lib/payment";
import { log } from "@/lib/log";

// Requires an Idempotency-Key header so client retries never create duplicate orders.
export const POST = instrument("/api/checkout", async (req, _ctx, requestId) => {
  const key = req.headers.get("idempotency-key");
  if (!key || key.length > 100) {
    return Response.json({ error: "idempotency_key_required" }, { status: 400 });
  }

  const scenario = activeScenario();
  // S01: the "new release" crashes in checkout. S03: a slow query adds latency.
  if (scenario === "S01_bad_deployment") throw new InjectedFault("TypeError: cannot read properties of undefined (reading 'total')");
  if (scenario === "S03_slow_query") await sleep(1500);

  const existing = findByKey(key);
  if (existing) return Response.json({ order: existing, replayed: true });

  const { lines, totalCents } = detail(await readCart());
  if (lines.length === 0) return Response.json({ error: "cart_empty" }, { status: 400 });

  let payment;
  try {
    payment = await authorize(totalCents);
  } catch (err) {
    if (err instanceof PaymentTimeout) {
      log("error", "payment_timeout", { request_id: requestId, total_cents: totalCents, error: err.message });
      return Response.json({ error: "payment_timeout" }, { status: 504 });
    }
    throw err;
  }
  if (!payment.approved) {
    log("warning", "payment_declined", { request_id: requestId, total_cents: totalCents });
    return Response.json({ error: "payment_declined" }, { status: 402 });
  }

  const order = saveOrder(key, lines, totalCents, payment.authorizationId);
  await writeCart([]);
  log("info", "order_created", { request_id: requestId, order_id: order.id, total_cents: totalCents });
  return Response.json({ order, replayed: false }, { status: 201 });
});
