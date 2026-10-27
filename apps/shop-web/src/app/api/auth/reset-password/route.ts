import { instrument } from "@/lib/handler";
import { rateLimitAuth, requireAuthConfig } from "@/lib/authRoutes";
import { consumeResetToken } from "@/lib/passwordReset";
import { validatePassword } from "@/lib/users";

// Body: { token, password }.
export const POST = instrument("/api/auth/reset-password", async (req) => {
  const off = requireAuthConfig();
  if (off) return off;
  const limited = await rateLimitAuth(req, "reset-password", 10, 300);
  if (limited) return limited;
  const body = (await req.json().catch(() => null)) as { token?: unknown; password?: unknown } | null;
  if (typeof body?.token !== "string" || !body.token) return Response.json({ error: "invalid_input" }, { status: 400 });
  const problem = validatePassword(body.password);
  if (problem) return Response.json({ error: "invalid_input", message: problem }, { status: 400 });

  const ok = await consumeResetToken(body.token, body.password as string);
  if (!ok) return Response.json({ error: "invalid_or_expired_token" }, { status: 400 });
  return Response.json({ ok: true });
});
