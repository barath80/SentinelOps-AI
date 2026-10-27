import { instrument } from "@/lib/handler";
import { getOrder, publicView } from "@/lib/orders";
import { getSession } from "@/lib/session";

export const GET = instrument("/api/orders/[id]", async (_req, ctx) => {
  const { id } = await ctx.params;
  const order = await getOrder(id);
  if (!order) return Response.json({ error: "not_found" }, { status: 404 });
  const session = await getSession();
  // Someone else's order looks like it does not exist.
  if (order.userId && order.userId !== session?.userId) return Response.json({ error: "not_found" }, { status: 404 });
  return Response.json({ order: publicView(order, session?.userId ?? null) });
});
