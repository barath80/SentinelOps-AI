import { instrument } from "@/lib/handler";
import { listOrders, publicView } from "@/lib/orders";
import { getSession } from "@/lib/session";

export const GET = instrument("/api/orders", async () => {
  const session = await getSession();
  if (!session) return Response.json({ error: "sign_in_required" }, { status: 401 });
  const orders = await listOrders(session.userId);
  return Response.json({ orders: orders.map((o) => publicView(o, session.userId)) });
});
