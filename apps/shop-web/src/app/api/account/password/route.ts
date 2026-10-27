import { instrument } from "@/lib/handler";
import { getSession } from "@/lib/session";
import { changePassword, validatePassword } from "@/lib/users";

// Body: { currentPassword, newPassword }.
export const PATCH = instrument("/api/account/password", async (req) => {
  const session = await getSession();
  if (!session) return Response.json({ error: "sign_in_required" }, { status: 401 });
  const body = (await req.json().catch(() => null)) as { currentPassword?: unknown; newPassword?: unknown } | null;
  if (typeof body?.currentPassword !== "string") return Response.json({ error: "invalid_input" }, { status: 400 });
  const problem = validatePassword(body.newPassword);
  if (problem) return Response.json({ error: "invalid_input", message: problem }, { status: 400 });

  const ok = await changePassword(session.userId, body.currentPassword, body.newPassword as string);
  if (!ok) return Response.json({ error: "incorrect_password", message: "Your current password is incorrect." }, { status: 401 });
  return Response.json({ ok: true });
});
