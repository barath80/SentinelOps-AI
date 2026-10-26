import { instrument } from "@/lib/handler";
import { getOrder } from "@/lib/orders";

export const GET = instrument("/api/orders/[id]", async (_req, ctx) => {
  const { id } = await ctx.params;
  const order = getOrder(id);
  if (!order) return Response.json({ error: "not_found" }, { status: 404 });
  return Response.json({ order });
});
