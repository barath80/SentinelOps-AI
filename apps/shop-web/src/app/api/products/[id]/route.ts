import { instrument } from "@/lib/handler";
import { getProduct } from "@/lib/products";

export const GET = instrument("/api/products/[id]", async (_req, ctx) => {
  const { id } = await ctx.params;
  const product = getProduct(id);
  if (!product) return Response.json({ error: "not_found" }, { status: 404 });
  return Response.json({ product });
});
