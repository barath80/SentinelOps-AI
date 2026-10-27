import { instrument } from "@/lib/handler";
import { rateLimitAuth, requireAuthConfig } from "@/lib/authRoutes";
import { createSession } from "@/lib/session";
import { verifyPassword } from "@/lib/users";

// Body: { email, password }. One generic error for unknown email and wrong password alike.
export const POST = instrument("/api/auth/login", async (req) => {
  const off = requireAuthConfig();
  if (off) return off;
  const limited = await rateLimitAuth(req, "login", 10, 60);
  if (limited) return limited;
  const body = (await req.json().catch(() => null)) as { email?: unknown; password?: unknown } | null;
  if (typeof body?.email !== "string" || typeof body?.password !== "string" || body.password.length > 200) {
    return Response.json({ error: "invalid_input" }, { status: 400 });
  }
  const user = await verifyPassword(body.email, body.password);
  if (!user) return Response.json({ error: "invalid_credentials", message: "Incorrect email or password." }, { status: 401 });
  await createSession({ userId: user.id, name: user.name, email: user.email });
  return Response.json({ user: { name: user.name, email: user.email } });
});
