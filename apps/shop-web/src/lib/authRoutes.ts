import { authConfigured } from "./session";

// Shared helpers for the auth route handlers.

export const notConfigured = () =>
  Response.json({ error: "auth_not_configured", hint: "set AUTH_SECRET (32+ characters)" }, { status: 503 });

export const requireAuthConfig = () => (authConfigured() ? null : notConfigured());

// Response.redirect() returns immutable headers, which the telemetry wrapper needs to annotate,
// so redirects are built by hand. Only relative, same-site locations are produced.
export const redirect = (location: string, status = 303) => new Response(null, { status, headers: { location } });
