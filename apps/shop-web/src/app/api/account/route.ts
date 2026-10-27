import { instrument } from "@/lib/handler";
import { createSession, getSession } from "@/lib/session";
import { updateProfile } from "@/lib/users";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

// Body: { name, email }.
export const PATCH = instrument("/api/account", async (req) => {
  const session = await getSession();
  if (!session) return Response.json({ error: "sign_in_required" }, { status: 401 });
  const body = (await req.json().catch(() => null)) as { name?: unknown; email?: unknown } | null;
  if (typeof body?.name !== "string" || !body.name.trim() || body.name.length > 60) {
    return Response.json({ error: "invalid_input", message: "Enter your name (up to 60 characters)." }, { status: 400 });
  }
  if (typeof body?.email !== "string" || !EMAIL_RE.test(body.email.trim()) || body.email.length > 254) {
    return Response.json({ error: "invalid_input", message: "Enter a valid email address." }, { status: 400 });
  }

  const result = await updateProfile(session.userId, body.name, body.email);
  if (result === "email_taken") {
    return Response.json({ error: "email_taken", message: "That email is already in use." }, { status: 409 });
  }
  await createSession({ userId: result.id, name: result.name, email: result.email });
  return Response.json({ user: { name: result.name, email: result.email } });
});
