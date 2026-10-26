// Creates the shop tables. Safe to re-run. Usage: npm run db:migrate
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

console.log("migration ok");
