import { instrument } from "@/lib/handler";
import { rateLimitAuth, requireAuthConfig } from "@/lib/authRoutes";
import { createSession } from "@/lib/session";
import { createPasswordUser, validateSignup } from "@/lib/users";

// Body: { email, name, password }. Never logs the email or password.
export const POST = instrument("/api/auth/signup", async (req) => {
  const off = requireAuthConfig();
  if (off) return off;
  const limited = await rateLimitAuth(req, "signup", 10, 60);
  if (limited) return limited;
  const body = (await req.json().catch(() => null)) as { email?: unknown; name?: unknown; password?: unknown } | null;
  const problem = validateSignup(body ?? {});
  if (problem) return Response.json({ error: "invalid_input", message: problem }, { status: 400 });
  const user = await createPasswordUser(body!.email as string, body!.name as string, body!.password as string);
  if (user === "exists") {
    return Response.json({ error: "email_taken", message: "An account with this email already exists. Sign in instead." }, { status: 409 });
  }
  await createSession({ userId: user.id, name: user.name, email: user.email });
  return Response.json({ user: { name: user.name, email: user.email } }, { status: 201 });
});
