// Minimal in-memory stand-in for the Neon `sql` tagged-template client, covering exactly the
// queries the shop issues today. Used by the unit tests, and by local end-to-end runs with
// SHOP_DB=memory so test traffic never writes to a real database (see db.ts).
export type FakeRow = Record<string, unknown>;

export const ordersTable: FakeRow[] = [];
export const usersTable: FakeRow[] = [];
export const rateLimitsTable: FakeRow[] = [];
export const passwordResetTokensTable: FakeRow[] = [];
export const wishlistItemsTable: FakeRow[] = [];
export const addressesTable: FakeRow[] = [];

export async function memorySql(strings: readonly string[], ...values: unknown[]): Promise<FakeRow[]> {
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
  if (/FROM users WHERE id = /.test(text)) {
    const [id] = values;
    return usersTable.filter((u) => u.id === id);
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
  if (/UPDATE users SET password_hash/.test(text)) {
    const [hash, id] = values;
    const row = usersTable.find((u) => u.id === id);
    if (row) row.password_hash = hash;
    return row ? [row] : [];
  }
  if (/UPDATE users SET name/.test(text)) {
    const [name, email, id] = values;
    const row = usersTable.find((u) => u.id === id);
    if (row) {
      row.name = name;
      row.email = email;
    }
    return row ? [row] : [];
  }

  if (/INSERT INTO rate_limits/.test(text)) {
    const [key, windowSeconds] = values as [string, number];
    const now = new Date();
    let row = rateLimitsTable.find((r) => r.key === key);
    const expired = row && now.getTime() - new Date(row.window_start as string).getTime() >= (windowSeconds as number) * 1000;
    if (!row) {
      row = { key, count: 1, window_start: now.toISOString() };
      rateLimitsTable.push(row);
    } else if (expired) {
      row.count = 1;
      row.window_start = now.toISOString();
    } else {
      row.count = (row.count as number) + 1;
    }
    return [row];
  }

  if (/INSERT INTO password_reset_tokens/.test(text)) {
    const [tokenHash, userId, ttlSeconds] = values as [string, string, number];
    const row: FakeRow = {
      token_hash: tokenHash,
      user_id: userId,
      expires_at: new Date(Date.now() + (ttlSeconds as number) * 1000).toISOString(),
      used_at: null,
    };
    passwordResetTokensTable.push(row);
    return [row];
  }
  if (/SELECT user_id FROM password_reset_tokens/.test(text)) {
    const [tokenHash] = values;
    const row = passwordResetTokensTable.find(
      (r) => r.token_hash === tokenHash && !r.used_at && new Date(r.expires_at as string).getTime() > Date.now(),
    );
    return row ? [row] : [];
  }
  if (/UPDATE password_reset_tokens SET used_at/.test(text)) {
    const [tokenHash] = values;
    const row = passwordResetTokensTable.find((r) => r.token_hash === tokenHash);
    if (row) row.used_at = new Date().toISOString();
    return row ? [row] : [];
  }

  if (/SELECT 1 FROM wishlist_items/.test(text)) {
    const [userId, productId] = values;
    return wishlistItemsTable.some((w) => w.user_id === userId && w.product_id === productId) ? [{ "1": 1 }] : [];
  }
  if (/SELECT product_id FROM wishlist_items/.test(text)) {
    const [userId] = values;
    return wishlistItemsTable
      .filter((w) => w.user_id === userId)
      .sort((a, b) => new Date(b.created_at as string).getTime() - new Date(a.created_at as string).getTime());
  }
  if (/INSERT INTO wishlist_items/.test(text)) {
    const [userId, productId] = values;
    if (!wishlistItemsTable.some((w) => w.user_id === userId && w.product_id === productId)) {
      wishlistItemsTable.push({ user_id: userId, product_id: productId, created_at: new Date().toISOString() });
    }
    return [];
  }
  if (/DELETE FROM wishlist_items/.test(text)) {
    const [userId, productId] = values;
    const idx = wishlistItemsTable.findIndex((w) => w.user_id === userId && w.product_id === productId);
    if (idx >= 0) wishlistItemsTable.splice(idx, 1);
    return [];
  }

  if (/FROM addresses WHERE user_id/.test(text)) {
    const [userId] = values;
    return addressesTable
      .filter((a) => a.user_id === userId)
      .sort((a, b) => new Date(a.created_at as string).getTime() - new Date(b.created_at as string).getTime());
  }
  if (/INSERT INTO addresses/.test(text)) {
    const [id, userId, label, fullName, line1, city, postalCode, country] = values;
    const row: FakeRow = {
      id, user_id: userId, label, full_name: fullName, line1, city, postal_code: postalCode, country,
      is_default: false, created_at: new Date().toISOString(),
    };
    addressesTable.push(row);
    return [row];
  }
  if (/DELETE FROM addresses/.test(text)) {
    const [id, userId] = values;
    const idx = addressesTable.findIndex((a) => a.id === id && a.user_id === userId);
    if (idx >= 0) addressesTable.splice(idx, 1);
    return [];
  }

  throw new Error(`fakeDb: unhandled query: ${text}`);
}

export function resetMemoryDb(): void {
  for (const t of [ordersTable, usersTable, rateLimitsTable, passwordResetTokensTable, wishlistItemsTable, addressesTable]) t.length = 0;
}
