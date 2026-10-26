import { neon } from "@neondatabase/serverless";
import type { DetailedLine } from "./cart";

export type Order = {
  id: string;
  idempotencyKey: string;
  createdAt: string;
  totalCents: number;
  lines: { id: string; name: string; qty: number; lineCents: number }[];
  authorizationId: string;
};

type Row = {
  id: string;
  idempotency_key: string;
  created_at: string | Date;
  total_cents: number;
  lines: Order["lines"];
  authorization_id: string;
};

// HTTP-based driver: no connection pool to manage in serverless functions.
function db() {
  const url = process.env.DATABASE_URL;
  if (!url) throw new Error("DATABASE_URL is not set");
  return neon(url);
}

function toOrder(r: Row): Order {
  return {
    id: r.id,
    idempotencyKey: r.idempotency_key,
    createdAt: new Date(r.created_at).toISOString(),
    totalCents: r.total_cents,
    lines: r.lines,
    authorizationId: r.authorization_id,
  };
}

export async function findByKey(key: string): Promise<Order | undefined> {
  const rows = (await db()`SELECT * FROM orders WHERE idempotency_key = ${key}`) as Row[];
  return rows[0] && toOrder(rows[0]);
}

export async function getOrder(id: string): Promise<Order | undefined> {
  const rows = (await db()`SELECT * FROM orders WHERE id = ${id}`) as Row[];
  return rows[0] && toOrder(rows[0]);
}

// Atomic on the idempotency key: two concurrent requests with the same key create one order.
// Returns the existing order (created=false) when the key was already used.
export async function saveOrder(
  idempotencyKey: string,
  lines: DetailedLine[],
  totalCents: number,
  authorizationId: string,
): Promise<{ order: Order; created: boolean }> {
  const id = `ord_${crypto.randomUUID().slice(0, 8)}`;
  const summary = lines.map((l) => ({ id: l.product.id, name: l.product.name, qty: l.qty, lineCents: l.lineCents }));
  const inserted = (await db()`
    INSERT INTO orders (id, idempotency_key, total_cents, lines, authorization_id)
    VALUES (${id}, ${idempotencyKey}, ${totalCents}, ${JSON.stringify(summary)}::jsonb, ${authorizationId})
    ON CONFLICT (idempotency_key) DO NOTHING
    RETURNING *`) as Row[];
  if (inserted[0]) return { order: toOrder(inserted[0]), created: true };
  const existing = await findByKey(idempotencyKey);
  if (!existing) throw new Error("order insert conflicted but no existing order found");
  return { order: existing, created: false };
}
