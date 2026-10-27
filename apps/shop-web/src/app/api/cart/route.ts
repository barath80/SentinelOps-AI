import { instrument } from "@/lib/handler";
import { detail, MAX_QTY, readCart, sameLine, writeCart } from "@/lib/cart";
import { colorOf, getProduct } from "@/lib/products";

export const GET = instrument("/api/cart", async () => {
  return Response.json(detail(await readCart()));
});

// Body: { id, qty, color?, add? }. With add=true qty is added to the line; otherwise it sets the
// line's quantity, and 0 removes it. Unknown colours fall back to the product's first colour.
export const POST = instrument("/api/cart", async (req) => {
  const body = (await req.json().catch(() => null)) as { id?: unknown; qty?: unknown; color?: unknown; add?: unknown } | null;
  if (!body || typeof body.id !== "string" || !Number.isInteger(body.qty)) {
    return Response.json({ error: "invalid_body" }, { status: 400 });
  }
  const product = getProduct(body.id);
  if (!product) return Response.json({ error: "unknown_product" }, { status: 404 });
  const color = colorOf(product, typeof body.color === "string" ? body.color : null).name;
  const lines = await readCart();
  const current = lines.find((l) => sameLine(l, product.id, color))?.qty ?? 0;
  const qty = body.add === true ? current + (body.qty as number) : (body.qty as number);
  if (qty < 0 || qty > MAX_QTY) return Response.json({ error: "invalid_quantity", max: MAX_QTY }, { status: 400 });

  const rest = lines.filter((l) => !sameLine(l, product.id, color));
  const next = qty > 0 ? [...rest, { id: product.id, qty, color }] : rest;
  await writeCart(next);
  return Response.json(detail(next));
});
