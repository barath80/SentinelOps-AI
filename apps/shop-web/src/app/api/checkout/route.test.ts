import { describe, expect, it } from "vitest";
import { cookieStore } from "../../../test/setup";
import { getProduct, PRODUCTS } from "../../../lib/products";
import { POST } from "./route";

const ctx = { params: Promise.resolve({}) };

function putCartLine(productId: string, qty = 1) {
  const p = getProduct(productId)!;
  cookieStore.set("cart", { value: JSON.stringify([{ id: p.id, qty, color: p.colors[0].name }]) });
}

function request(body: unknown, headers: Record<string, string> = {}) {
  return new Request("http://localhost/api/checkout", {
    method: "POST",
    headers: { "content-type": "application/json", "idempotency-key": "test-key-1", ...headers },
    body: JSON.stringify(body),
  });
}

describe("POST /api/checkout", () => {
  it("requires an Idempotency-Key header", async () => {
    putCartLine("p1");
    const req = new Request("http://localhost/api/checkout", { method: "POST", body: JSON.stringify({}) });
    const res = await POST(req, ctx);
    expect(res.status).toBe(400);
    expect((await res.json()).error).toBe("idempotency_key_required");
  });

  it("rejects an empty cart", async () => {
    const res = await POST(request({}), ctx);
    expect(res.status).toBe(400);
    expect((await res.json()).error).toBe("cart_empty");
  });

  it("rejects invalid shipping", async () => {
    putCartLine("p1");
    const res = await POST(request({ shipping: { fullName: "" } }), ctx);
    expect(res.status).toBe(400);
    expect((await res.json()).error).toBe("invalid_shipping");
  });

  it("places a guest order and clears the cart", async () => {
    putCartLine("p1", 2);
    const res = await POST(request({}), ctx);
    expect(res.status).toBe(201);
    const body = await res.json();
    expect(body.replayed).toBe(false);
    expect(body.order.id).toMatch(/^ord_/);
    expect(body.order.userId).toBeUndefined(); // publicView strips it for the response shape
    expect(await (await import("../../../lib/cart")).readCart()).toEqual([]);
  });

  it("replays the same order for a repeated idempotency key", async () => {
    putCartLine("p1", 1);
    const first = await (await POST(request({}), ctx)).json();
    putCartLine("p1", 1); // a client retry would resend the same cart + key
    const second = await (await POST(request({}), ctx)).json();
    expect(second.replayed).toBe(true);
    expect(second.order.id).toBe(first.order.id);
  });

  it("declines orders over the $5,000 threshold", async () => {
    const expensive = [...PRODUCTS].sort((a, b) => b.priceCents - a.priceCents)[0];
    putCartLine(expensive.id, 10); // 10 is the per-line quantity cap
    const res = await POST(request({}), ctx);
    expect(res.status).toBe(402);
    expect((await res.json()).error).toBe("payment_declined");
  });
});
