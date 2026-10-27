import { instrument } from "@/lib/handler";
import { getSession } from "@/lib/session";

export const GET = instrument("/api/auth/me", async () => {
  const s = await getSession();
  return Response.json({ user: s ? { name: s.name, email: s.email } : null });
});
