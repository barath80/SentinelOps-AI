import { jwtVerify, SignJWT } from "jose";
import { cookies } from "next/headers";

// Sessions are signed JWTs in an httpOnly cookie (no session table needed on serverless).
// AUTH_SECRET must be at least 32 characters; without it sign-in is disabled (fail closed).

export type Session = { userId: string; name: string; email: string };

const COOKIE = "session";
const MAX_AGE = 60 * 60 * 24 * 7;

export function authConfigured(): boolean {
  return (process.env.AUTH_SECRET ?? "").length >= 32;
}

export function googleConfigured(): boolean {
  return authConfigured() && !!process.env.AUTH_GOOGLE_ID && !!process.env.AUTH_GOOGLE_SECRET;
}

function key(): Uint8Array {
  if (!authConfigured()) throw new Error("AUTH_SECRET is not set (needs 32+ characters)");
  return new TextEncoder().encode(process.env.AUTH_SECRET);
}

export const cookieSecurity = () => ({
  httpOnly: true,
  sameSite: "lax" as const,
  secure: process.env.NODE_ENV === "production",
  path: "/",
});

export async function createSession(s: Session): Promise<void> {
  const token = await new SignJWT({ name: s.name, email: s.email })
    .setProtectedHeader({ alg: "HS256" })
    .setSubject(s.userId)
    .setIssuedAt()
    .setExpirationTime(`${MAX_AGE}s`)
    .sign(key());
  (await cookies()).set(COOKIE, token, { ...cookieSecurity(), maxAge: MAX_AGE });
}

export async function getSession(): Promise<Session | null> {
  if (!authConfigured()) return null;
  const token = (await cookies()).get(COOKIE)?.value;
  if (!token) return null;
  try {
    const { payload } = await jwtVerify(token, key(), { algorithms: ["HS256"] });
    if (!payload.sub) return null;
    return { userId: payload.sub, name: String(payload.name ?? ""), email: String(payload.email ?? "") };
  } catch {
    return null; // expired or tampered
  }
}

export async function clearSession(): Promise<void> {
  (await cookies()).delete(COOKIE);
}

// Only same-site relative paths are allowed as post-login destinations (no open redirects).
export function safeNext(next: string | null | undefined): string {
  return next && next.startsWith("/") && !next.startsWith("//") && !next.startsWith("/\\") ? next : "/";
}
