// Creates and upgrades the shop tables. Safe to re-run. Usage: npm run db:migrate
import dns from "node:dns";
import net from "node:net";
import { neon } from "@neondatabase/serverless";

// Same network tuning as src/instrumentation.ts (slow/broken IPv6 networks).
dns.setDefaultResultOrder("ipv4first");
net.setDefaultAutoSelectFamilyAttemptTimeout(2000);

const url = process.env.DATABASE_URL;
if (!url) {
  console.error("DATABASE_URL is not set (put it in .env.local)");
  process.exit(1);
}

const sql = neon(url);

await sql`
  CREATE TABLE IF NOT EXISTS orders (
    id              TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    total_cents     INTEGER NOT NULL CHECK (total_cents >= 0),
    lines           JSONB NOT NULL,
    authorization_id TEXT NOT NULL
  )`;

await sql`
  CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    email         TEXT NOT NULL UNIQUE,
    name          TEXT NOT NULL,
    password_hash TEXT,
    google_sub    TEXT UNIQUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
  )`;

// Orders placed while signed in belong to that user; guest orders keep user_id NULL.
await sql`ALTER TABLE orders ADD COLUMN IF NOT EXISTS user_id TEXT REFERENCES users(id) ON DELETE SET NULL`;
await sql`ALTER TABLE orders ADD COLUMN IF NOT EXISTS shipping JSONB`;
await sql`ALTER TABLE orders ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'placed'`;
await sql`CREATE INDEX IF NOT EXISTS orders_user_created ON orders (user_id, created_at DESC)`;

await sql`
  CREATE TABLE IF NOT EXISTS password_reset_tokens (
    token_hash TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TIMESTAMPTZ NOT NULL,
    used_at    TIMESTAMPTZ
  )`;

// Fixed-window rate limiting shared across auth routes (login, signup, password reset).
await sql`
  CREATE TABLE IF NOT EXISTS rate_limits (
    key          TEXT PRIMARY KEY,
    count        INTEGER NOT NULL DEFAULT 0,
    window_start TIMESTAMPTZ NOT NULL
  )`;

await sql`
  CREATE TABLE IF NOT EXISTS wishlist_items (
    user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    product_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, product_id)
  )`;

await sql`
  CREATE TABLE IF NOT EXISTS addresses (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    label       TEXT NOT NULL,
    full_name   TEXT NOT NULL,
    line1       TEXT NOT NULL,
    city        TEXT NOT NULL,
    postal_code TEXT NOT NULL,
    country     TEXT NOT NULL,
    is_default  BOOLEAN NOT NULL DEFAULT false,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
  )`;
await sql`CREATE INDEX IF NOT EXISTS addresses_user ON addresses (user_id, created_at)`;

console.log("migration ok");
