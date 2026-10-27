import type { DetailedLine } from "./cart";
import { db } from "./db";

// email is optional: signed-in orders don't need it (the account already has one), but a guest
// order has no account to fall back on, so the checkout UI collects it from guests.
export type Shipping = { fullName: string; line1: string; city: string; postalCode: string; country: string; email?: string };

export type OrderLine = { id: string; name: string; qty: number; lineCents: number; color?: string; colorHex?: string; art?: string };

export type Order = {
  id: string;
  idempotencyKey: string;
  createdAt: string;
  totalCents: number;
  lines: OrderLine[];
  authorizationId: string;
  userId: string | null;
  shipping: Shipping | null;
  status: string;
};

type Row = {
  id: string;
  idempotency_key: string;
  created_at: string | Date;
  total_cents: number;
  lines: OrderLine[];
  authorization_id: string;
  user_id: string | null;
  shipping: Shipping | null;
  status: string | null;
};

function toOrder(r: Row): Order {
  return {
    id: r.id,
    idempotencyKey: r.idempotency_key,
    createdAt: new Date(r.created_at).toISOString(),
    totalCents: r.total_cents,
    lines: r.lines,
    authorizationId: r.authorization_id,
    userId: r.user_id ?? null,
    shipping: r.shipping ?? null,
    status: r.status ?? "placed",
  };
}

export function validateShipping(s: unknown): Shipping | null | "invalid" {
  if (s === undefined || s === null) return null;
  if (typeof s !== "object") return "invalid";
  const o = s as Record<string, unknown>;
  const keys: (keyof Omit<Shipping, "email">)[] = ["fullName", "line1", "city", "postalCode", "country"];
  const out = {} as Shipping;
  for (const k of keys) {
    const v = o[k];
    if (typeof v !== "string" || !v.trim() || v.length > 120) return "invalid";
    out[k] = v.trim();
  }
  if (o.email !== undefined) {
    if (typeof o.email !== "string" || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(o.email.trim()) || o.email.length > 254) return "invalid";
    out.email = o.email.trim();
  }
  return out;
}

export async function findByKey(key: string): Promise<Order | undefined> {
  const rows = (await db()`SELECT * FROM orders WHERE idempotency_key = ${key}`) as Row[];
  return rows[0] && toOrder(rows[0]);
}

export async function getOrder(id: string): Promise<Order | undefined> {
  const rows = (await db()`SELECT * FROM orders WHERE id = ${id}`) as Row[];
  return rows[0] && toOrder(rows[0]);
}

export async function listOrders(userId: string, limit = 50): Promise<Order[]> {
  const rows = (await db()`SELECT * FROM orders WHERE user_id = ${userId} ORDER BY created_at DESC LIMIT ${limit}`) as Row[];
  return rows.map(toOrder);
}

// Atomic on the idempotency key: two concurrent requests with the same key create one order.
// Returns the existing order (created=false) when the key was already used.
export async function saveOrder(
  idempotencyKey: string,
  lines: DetailedLine[],
  totalCents: number,
  authorizationId: string,
  userId: string | null = null,
  shipping: Shipping | null = null,
): Promise<{ order: Order; created: boolean }> {
  // 64 random bits: order ids are not guessable.
  const id = `ord_${crypto.randomUUID().replace(/-/g, "").slice(0, 16)}`;
  const summary: OrderLine[] = lines.map((l) => ({
    id: l.product.id, name: l.product.name, qty: l.qty, lineCents: l.lineCents,
    color: l.color.name, colorHex: l.color.hex, art: l.product.art,
  }));
  const inserted = (await db()`
    INSERT INTO orders (id, idempotency_key, total_cents, lines, authorization_id, user_id, shipping)
    VALUES (${id}, ${idempotencyKey}, ${totalCents}, ${JSON.stringify(summary)}::jsonb, ${authorizationId},
            ${userId}, ${shipping ? JSON.stringify(shipping) : null}::jsonb)
    ON CONFLICT (idempotency_key) DO NOTHING
    RETURNING *`) as Row[];
  if (inserted[0]) return { order: toOrder(inserted[0]), created: true };
  const existing = await findByKey(idempotencyKey);
  if (!existing) throw new Error("order insert conflicted but no existing order found");
  return { order: existing, created: false };
}

// What a caller may see. A signed-in order's address is only shown to its owner. A guest order
// has no owner to restrict it to: the unguessable order id is itself the access credential, so
// anyone who holds it (the guest who just placed it, or a link they're shown) can see it.
export function publicView(o: Order, viewerId: string | null) {
  const own = o.userId === null || o.userId === viewerId;
  return { ...o, shipping: own ? o.shipping : null, userId: undefined, idempotencyKey: undefined };
}
