import { neon } from "@neondatabase/serverless";
import { instrument } from "@/lib/handler";

// Readiness check: reports whether the database is configured and reachable.
// Never echoes the connection string; only host name and a short error message.
export const GET = instrument("/api/health/db", async () => {
  const url = process.env.DATABASE_URL;
  if (!url) return Response.json({ configured: false, ok: false }, { status: 503 });

  let host = "unparseable";
  try {
    host = new URL(url).host;
  } catch {}

  try {
    const started = performance.now();
    const rows = await neon(url)`SELECT to_regclass('public.orders') IS NOT NULL AS orders_table`;
    return Response.json({
      configured: true,
      ok: true,
      host,
      orders_table: rows[0]?.orders_table === true,
      ms: Math.round(performance.now() - started),
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return Response.json({ configured: true, ok: false, host, error: message.slice(0, 200) }, { status: 503 });
  }
});
