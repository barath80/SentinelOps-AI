import { neon } from "@neondatabase/serverless";
import { instrument } from "@/lib/handler";

// Readiness check: reports whether the database is configured and reachable.
// Never echoes the connection string; only host name and a short error message.
export const GET = instrument("/api/health/db", async () => {
  const url = process.env.DATABASE_URL;
  if (!url) return Response.json({ configured: false, ok: false }, { status: 503 });

  // Shape of the value only (never the value): helps spot paste mistakes.
  const shape = {
    length: url.length,
    starts_with_postgres_scheme: /^postgres(ql)?:\/\//.test(url),
    has_name_prefix: /^[A-Z_]+=/.test(url),
    has_quotes: /^["']|["']$/.test(url),
    has_whitespace: /\s/.test(url),
  };

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
    // Driver errors can quote the connection string (including the password), so never
    // pass them through: classify known cases and redact anything URL-like from the rest.
    const message = err instanceof Error ? err.message : String(err);
    const error = /connection string/i.test(message)
      ? "invalid_connection_string (value must be exactly postgresql://..., without a NAME= prefix or quotes)"
      : message.replace(/\S*:\/\/\S*/g, "[redacted]").slice(0, 120);
    return Response.json({ configured: true, ok: false, host, shape, error }, { status: 503 });
  }
});
