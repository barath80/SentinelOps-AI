import { deleteAddress } from "@/lib/addresses";
import { instrument } from "@/lib/handler";
import { getSession } from "@/lib/session";

export const DELETE = instrument("/api/account/addresses/[id]", async (_req, ctx) => {
  const session = await getSession();
  if (!session) return Response.json({ error: "sign_in_required" }, { status: 401 });
  const { id } = await ctx.params;
  await deleteAddress(session.userId, id);
  return Response.json({ ok: true });
});
