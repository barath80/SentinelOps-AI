import bcrypt from "bcryptjs";
import { db } from "./db";
import { findUserByEmail } from "./users";

const TOKEN_TTL_SECONDS = 60 * 60; // 1 hour

// Only the hash is stored, so a leaked database row can't be used to reset anyone's password.
async function hashToken(token: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(token));
  return Buffer.from(digest).toString("hex");
}

export async function createResetToken(email: string): Promise<string | null> {
  const user = await findUserByEmail(email);
  if (!user) return null;
  const token = `${crypto.randomUUID()}${crypto.randomUUID()}`.replace(/-/g, "");
  const tokenHash = await hashToken(token);
  await db()`
    INSERT INTO password_reset_tokens (token_hash, user_id, expires_at)
    VALUES (${tokenHash}, ${user.id}, now() + make_interval(secs => ${TOKEN_TTL_SECONDS}))`;
  return token;
}

export async function consumeResetToken(token: string, newPassword: string): Promise<boolean> {
  const tokenHash = await hashToken(token);
  const rows = (await db()`
    SELECT user_id FROM password_reset_tokens
    WHERE token_hash = ${tokenHash} AND used_at IS NULL AND expires_at > now()`) as { user_id: string }[];
  const row = rows[0];
  if (!row) return false;
  const hash = await bcrypt.hash(newPassword, 10);
  await db()`UPDATE users SET password_hash = ${hash} WHERE id = ${row.user_id}`;
  await db()`UPDATE password_reset_tokens SET used_at = now() WHERE token_hash = ${tokenHash}`;
  return true;
}
