import { instrument } from "@/lib/handler";
import { getSession } from "@/lib/session";
import { removeFromWishlist } from "@/lib/wishlist";

export const DELETE = instrument("/api/wishlist/[id]", async (_req, ctx) => {
  const session = await getSession();
  if (!session) return Response.json({ error: "sign_in_required" }, { status: 401 });
  const { id } = await ctx.params;
  await removeFromWishlist(session.userId, id);
  return Response.json({ ok: true });
});
