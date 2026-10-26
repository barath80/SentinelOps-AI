import type { DetailedLine } from "./cart";

export type Order = {
  id: string;
  idempotencyKey: string;
  createdAt: string;
  totalCents: number;
  lines: { id: string; name: string; qty: number; lineCents: number }[];
  authorizationId: string;
};

// Phase 1 storage is process memory: fine locally, best-effort on serverless
// (instances are recycled). A durable store replaces this behind the same functions.
const byId = new Map<string, Order>();
const byKey = new Map<string, string>();

export function findByKey(key: string): Order | undefined {
  const id = byKey.get(key);
  return id ? byId.get(id) : undefined;
}

export function getOrder(id: string): Order | undefined {
  return byId.get(id);
}

export function saveOrder(
  idempotencyKey: string,
  lines: DetailedLine[],
  totalCents: number,
  authorizationId: string,
): Order {
  const order: Order = {
    id: `ord_${crypto.randomUUID().slice(0, 8)}`,
    idempotencyKey,
    createdAt: new Date().toISOString(),
    totalCents,
    lines: lines.map((l) => ({ id: l.product.id, name: l.product.name, qty: l.qty, lineCents: l.lineCents })),
    authorizationId,
  };
  byId.set(order.id, order);
  byKey.set(idempotencyKey, order.id);
  return order;
}
