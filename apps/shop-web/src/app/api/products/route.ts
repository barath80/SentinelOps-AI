import { instrument } from "@/lib/handler";
import { listProducts } from "@/lib/products";

export const GET = instrument("/api/products", async (req) => {
  const q = new URL(req.url).searchParams.get("q") ?? undefined;
  return Response.json({ products: listProducts(q) });
});
