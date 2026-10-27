import { instrument } from "@/lib/handler";
import { getProduct } from "@/lib/products";
import { getSession } from "@/lib/session";
import { addToWishlist, listWishlistProductIds } from "@/lib/wishlist";

export const GET = instrument("/api/wishlist", async () => {
  const session = await getSession();
  if (!session) return Response.json({ error: "sign_in_required" }, { status: 401 });
  const ids = await listWishlistProductIds(session.userId);
  const products = ids.flatMap((id) => {
    const p = getProduct(id);
    return p ? [p] : [];
  });
  return Response.json({ products });
});

// Body: { productId }.
export const POST = instrument("/api/wishlist", async (req) => {
  const session = await getSession();
  if (!session) return Response.json({ error: "sign_in_required" }, { status: 401 });
  const body = (await req.json().catch(() => null)) as { productId?: unknown } | null;
  if (typeof body?.productId !== "string") return Response.json({ error: "invalid_body" }, { status: 400 });
  if (!getProduct(body.productId)) return Response.json({ error: "unknown_product" }, { status: 404 });
  await addToWishlist(session.userId, body.productId);
  return Response.json({ ok: true }, { status: 201 });
});
