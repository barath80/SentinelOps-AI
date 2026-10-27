import bcrypt from "bcryptjs";
import { db } from "./db";

export type User = { id: string; email: string; name: string; passwordHash: string | null; googleSub: string | null };
type Row = { id: string; email: string; name: string; password_hash: string | null; google_sub: string | null };

const toUser = (r: Row): User => ({ id: r.id, email: r.email, name: r.name, passwordHash: r.password_hash, googleSub: r.google_sub });

// Compared against when the email is unknown, so a failed login takes the same time either way.
let dummyHash: string | null = null;
const dummy = () => (dummyHash ??= bcrypt.hashSync("placeholder-for-timing-only", 10));

export const normalizeEmail = (e: string) => e.trim().toLowerCase();

export function validateSignup(input: { email?: unknown; password?: unknown; name?: unknown }): string | null {
  if (typeof input.email !== "string" || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(input.email.trim()) || input.email.length > 254)
    return "Enter a valid email address.";
  if (typeof input.name !== "string" || !input.name.trim() || input.name.length > 60) return "Enter your name (up to 60 characters).";
  if (typeof input.password !== "string" || input.password.length < 8) return "Use a password of at least 8 characters.";
  if (new TextEncoder().encode(input.password).length > 72) return "Use a password of at most 72 bytes.";
  return null;
}

export async function findUserByEmail(email: string): Promise<User | null> {
  const rows = (await db()`SELECT * FROM users WHERE email = ${normalizeEmail(email)}`) as Row[];
  return rows[0] ? toUser(rows[0]) : null;
}

export async function createPasswordUser(email: string, name: string, password: string): Promise<User | "exists"> {
  const hash = await bcrypt.hash(password, 10);
  const rows = (await db()`
    INSERT INTO users (id, email, name, password_hash)
    VALUES (${crypto.randomUUID()}, ${normalizeEmail(email)}, ${name.trim()}, ${hash})
    ON CONFLICT (email) DO NOTHING
    RETURNING *`) as Row[];
  return rows[0] ? toUser(rows[0]) : "exists";
}

export async function verifyPassword(email: string, password: string): Promise<User | null> {
  const user = await findUserByEmail(email);
  const ok = await bcrypt.compare(password, user?.passwordHash ?? dummy());
  return user && user.passwordHash && ok ? user : null;
}

// Google sign-in: match by Google account id; link to an existing email account only when Google
// says the email is verified (otherwise someone could claim another person's account).
export async function upsertGoogleUser(claims: { sub: string; email?: string; emailVerified?: boolean; name?: string }): Promise<User> {
  const bySub = (await db()`SELECT * FROM users WHERE google_sub = ${claims.sub}`) as Row[];
  if (bySub[0]) return toUser(bySub[0]);
  const email = claims.email ? normalizeEmail(claims.email) : null;
  if (email && claims.emailVerified) {
    const linked = (await db()`UPDATE users SET google_sub = ${claims.sub} WHERE email = ${email} AND google_sub IS NULL RETURNING *`) as Row[];
    if (linked[0]) return toUser(linked[0]);
  }
  if (!email || !claims.emailVerified) throw new Error("google_email_not_verified");
  const rows = (await db()`
    INSERT INTO users (id, email, name, google_sub)
    VALUES (${crypto.randomUUID()}, ${email}, ${(claims.name ?? email.split("@")[0]).slice(0, 60)}, ${claims.sub})
    RETURNING *`) as Row[];
  return toUser(rows[0]);
}
