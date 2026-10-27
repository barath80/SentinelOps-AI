import { db } from "./db";

// Fixed-window rate limiting backed by the existing Neon Postgres connection, rather than adding
// a new managed dependency (e.g. Upstash Redis) for what's currently modest-traffic auth traffic.
// Tradeoff: one DB round-trip per checked request, and no sub-window smoothing. If traffic grows
// enough for that to matter, @upstash/ratelimit is the natural upgrade path.
export async function checkRateLimit(
  key: string,
  limit: number,
  windowSeconds: number,
): Promise<{ allowed: boolean; retryAfterSeconds: number }> {
  const rows = (await db()`
    INSERT INTO rate_limits (key, count, window_start)
    VALUES (${key}, 1, now())
    ON CONFLICT (key) DO UPDATE SET
      count = CASE WHEN rate_limits.window_start < now() - make_interval(secs => ${windowSeconds})
                   THEN 1 ELSE rate_limits.count + 1 END,
      window_start = CASE WHEN rate_limits.window_start < now() - make_interval(secs => ${windowSeconds})
                     THEN now() ELSE rate_limits.window_start END
    RETURNING count, window_start`) as { count: number; window_start: string | Date }[];
  const row = rows[0];
  const windowStartMs = new Date(row.window_start).getTime();
  const retryAfterSeconds = Math.max(0, Math.ceil((windowStartMs + windowSeconds * 1000 - Date.now()) / 1000));
  return { allowed: row.count <= limit, retryAfterSeconds };
}

// Vercel (and most proxies) set x-forwarded-for; falls back to a constant so local dev without
// a proxy still gets a (shared) rate limit instead of throwing.
export function clientIp(req: Request): string {
  return req.headers.get("x-forwarded-for")?.split(",")[0]?.trim() || "unknown";
}

export function tooManyRequests(retryAfterSeconds: number): Response {
  return Response.json(
    { error: "too_many_requests" },
    { status: 429, headers: { "retry-after": String(retryAfterSeconds) } },
  );
}
