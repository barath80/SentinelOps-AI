import { addAddress, listAddresses } from "@/lib/addresses";
import { instrument } from "@/lib/handler";
import { validateShipping } from "@/lib/orders";
import { getSession } from "@/lib/session";

export const GET = instrument("/api/account/addresses", async () => {
  const session = await getSession();
  if (!session) return Response.json({ error: "sign_in_required" }, { status: 401 });
  return Response.json({ addresses: await listAddresses(session.userId) });
});

// Body: { label, ...Shipping }.
export const POST = instrument("/api/account/addresses", async (req) => {
  const session = await getSession();
  if (!session) return Response.json({ error: "sign_in_required" }, { status: 401 });
  const body = (await req.json().catch(() => null)) as { label?: unknown } | null;
  if (typeof body?.label !== "string" || !body.label.trim() || body.label.length > 40) {
    return Response.json({ error: "invalid_label" }, { status: 400 });
  }
  const shipping = validateShipping(body);
  if (shipping === "invalid" || shipping === null) return Response.json({ error: "invalid_address" }, { status: 400 });
  const address = await addAddress(session.userId, body.label.trim(), shipping);
  return Response.json({ address }, { status: 201 });
});
