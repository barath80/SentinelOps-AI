import { instrument } from "@/lib/handler";
import { clearSession } from "@/lib/session";

export const POST = instrument("/api/auth/logout", async () => {
  await clearSession();
  return Response.json({ ok: true });
});
