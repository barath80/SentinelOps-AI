import { afterEach, vi } from "vitest";

// Minimal in-memory stand-in for the Neon `sql` tagged-template client, covering exactly the
// queries `src/lib/orders.ts` and `src/lib/users.ts` issue today.
export type FakeRow = Record<string, unknown>;

export const ordersTable: FakeRow[] = [];
export const usersTable: FakeRow[] = [];

async function fakeSql(strings: readonly string[], ...values: unknown[]): Promise<FakeRow[]> {
  const text = strings.join("?");

  if (/FROM orders WHERE idempotency_key/.test(text)) {
    const [key] = values;
    return ordersTable.filter((o) => o.idempotency_key === key);
  }
  if (/FROM orders WHERE user_id/.test(text)) {
    const [userId, limit] = values;
    return ordersTable
      .filter((o) => o.user_id === userId)
      .sort((a, b) => new Date(b.created_at as string).getTime() - new Date(a.created_at as string).getTime())
      .slice(0, limit as number);
  }
  if (/FROM orders WHERE id = /.test(text)) {
    const [id] = values;
    return ordersTable.filter((o) => o.id === id);
  }
  if (/INSERT INTO orders/.test(text)) {
    const [id, idempotencyKey, totalCents, lines, authorizationId, userId, shipping] = values;
    if (ordersTable.some((o) => o.idempotency_key === idempotencyKey)) return [];
    const row: FakeRow = {
      id,
      idempotency_key: idempotencyKey,
      total_cents: totalCents,
      lines: JSON.parse(lines as string),
      authorization_id: authorizationId,
      user_id: userId,
      shipping: shipping ? JSON.parse(shipping as string) : null,
      status: "placed",
      created_at: new Date().toISOString(),
    };
    ordersTable.push(row);
    return [row];
  }

  if (/FROM users WHERE email/.test(text)) {
    const [email] = values;
    return usersTable.filter((u) => u.email === email);
  }
  if (/FROM users WHERE google_sub/.test(text)) {
    const [sub] = values;
    return usersTable.filter((u) => u.google_sub === sub);
  }
  if (/UPDATE users SET google_sub/.test(text)) {
    const [sub, email] = values;
    const row = usersTable.find((u) => u.email === email && !u.google_sub);
    if (!row) return [];
    row.google_sub = sub;
    return [row];
  }
  if (/INSERT INTO users/.test(text) && /password_hash/.test(text)) {
    const [id, email, name, hash] = values;
    if (usersTable.some((u) => u.email === email)) return [];
    const row: FakeRow = { id, email, name, password_hash: hash, google_sub: null };
    usersTable.push(row);
    return [row];
  }
  if (/INSERT INTO users/.test(text) && /google_sub/.test(text)) {
    const [id, email, name, sub] = values;
    const row: FakeRow = { id, email, name, password_hash: null, google_sub: sub };
    usersTable.push(row);
    return [row];
  }

  throw new Error(`fakeDb: unhandled query: ${text}`);
}

vi.mock("@/lib/db", () => ({ db: () => fakeSql }));

afterEach(() => {
  ordersTable.length = 0;
  usersTable.length = 0;
});
