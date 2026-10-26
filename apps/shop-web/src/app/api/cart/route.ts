import { instrument } from "@/lib/handler";
import { detail, MAX_QTY, readCart, writeCart } from "@/lib/cart";
import { getProduct } from "@/lib/products";

export const GET = instrument("/api/cart", async () => {
  return Response.json(detail(await readCart()));
});

// Body: { id: string, qty: number }. qty 0 removes the line; otherwise sets the quantity.
export const POST = instrument("/api/cart", async (req) => {
  const body = (await req.json().catch(() => null)) as { id?: unknown; qty?: unknown } | null;
  if (!body || typeof body.id !== "string" || !Number.isInteger(body.qty)) {
    return Response.json({ error: "invalid_body" }, { status: 400 });
  }
  const qty = body.qty as number;
  if (!getProduct(body.id)) return Response.json({ error: "unknown_product" }, { status: 404 });
  if (qty < 0 || qty > MAX_QTY) return Response.json({ error: "invalid_quantity" }, { status: 400 });

  const lines = (await readCart()).filter((l) => l.id !== body.id);
  if (qty > 0) lines.push({ id: body.id, qty });
  await writeCart(lines);
  return Response.json(detail(lines));
});
