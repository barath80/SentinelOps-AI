import { neon } from "@neondatabase/serverless";

// HTTP-based driver: no connection pool to manage in serverless functions.
export function db() {
  const url = process.env.DATABASE_URL;
  if (!url) throw new Error("DATABASE_URL is not set");
  return neon(url);
}
