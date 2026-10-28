import { neon } from "@neondatabase/serverless";
import { memorySql } from "./memoryDb";

// HTTP-based driver: no connection pool to manage in serverless functions.
// SHOP_DB=memory swaps in an in-memory store for local end-to-end runs, so test traffic never
// writes to a real database. It is refused on Vercel: a deployed shop always uses Postgres.
export function db() {
  if (process.env.SHOP_DB === "memory") {
    if (process.env.VERCEL) throw new Error("SHOP_DB=memory is for local runs only");
    return memorySql as unknown as ReturnType<typeof neon>;
  }
  const url = process.env.DATABASE_URL;
  if (!url) throw new Error("DATABASE_URL is not set");
  return neon(url);
}
