import { checkRateLimit, clientIp, tooManyRequests } from "./rateLimit";
import { authConfigured } from "./session";

// Shared helpers for the auth route handlers.

export const notConfigured = () =>
  Response.json({ error: "auth_not_configured", hint: "set AUTH_SECRET (32+ characters)" }, { status: 503 });

export const requireAuthConfig = () => (authConfigured() ? null : notConfigured());

// Keyed by IP + route, so a single caller can't exhaust another route's budget.
export async function rateLimitAuth(req: Request, route: string, limit: number, windowSeconds: number): Promise<Response | null> {
  const { allowed, retryAfterSeconds } = await checkRateLimit(`${route}:${clientIp(req)}`, limit, windowSeconds);
  return allowed ? null : tooManyRequests(retryAfterSeconds);
}

// Response.redirect() returns immutable headers, which the telemetry wrapper needs to annotate,
// so redirects are built by hand. Only relative, same-site locations are produced.
export const redirect = (location: string, status = 303) => new Response(null, { status, headers: { location } });
