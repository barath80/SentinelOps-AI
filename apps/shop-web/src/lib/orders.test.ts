import { describe, expect, it } from "vitest";
import { publicView, saveOrder, validateShipping, type Order } from "./orders";

const validShipping = { fullName: "Ada Lovelace", line1: "1 Analytical Engine Way", city: "London", postalCode: "AB1 2CD", country: "UK" };

describe("validateShipping", () => {
  it("returns null when shipping is omitted", () => {
    expect(validateShipping(undefined)).toBeNull();
    expect(validateShipping(null)).toBeNull();
  });

  it("accepts a fully filled-in address", () => {
    expect(validateShipping(validShipping)).toEqual(validShipping);
  });

  it("rejects a missing or blank field", () => {
    expect(validateShipping({ ...validShipping, city: "" })).toBe("invalid");
    expect(validateShipping({ ...validShipping, city: undefined })).toBe("invalid");
  });

  it("rejects a field over 120 characters", () => {
    expect(validateShipping({ ...validShipping, line1: "a".repeat(121) })).toBe("invalid");
  });

  it("accepts an optional, valid email", () => {
    expect(validateShipping({ ...validShipping, email: "guest@example.com" })).toEqual({ ...validShipping, email: "guest@example.com" });
  });

  it("rejects an invalid email when one is provided", () => {
    expect(validateShipping({ ...validShipping, email: "not-an-email" })).toBe("invalid");
  });
});

describe("publicView", () => {
  const base: Order = {
    id: "ord_1", idempotencyKey: "key_1", createdAt: new Date().toISOString(), totalCents: 1000,
    lines: [], authorizationId: "auth_1", userId: null, shipping: validShipping, status: "placed",
  };

  it("shows a guest order's shipping to anyone holding the order id (no owner to restrict it to)", () => {
    expect(publicView(base, null).shipping).toEqual(validShipping);
    expect(publicView(base, "some-other-user").shipping).toEqual(validShipping);
  });

  it("shows a signed-in order's shipping only to its owner", () => {
    const owned = { ...base, userId: "u1" };
    expect(publicView(owned, "u1").shipping).toEqual(validShipping);
    expect(publicView(owned, "u2").shipping).toBeNull();
    expect(publicView(owned, null).shipping).toBeNull();
  });

  it("never exposes userId or idempotencyKey", () => {
    const view = publicView(base, null);
    expect(view.userId).toBeUndefined();
    expect(view.idempotencyKey).toBeUndefined();
  });
});

describe("saveOrder", () => {
  it("is idempotent on the idempotency key", async () => {
    const first = await saveOrder("key_a", [], 500, "auth_a", null, null);
    const second = await saveOrder("key_a", [], 999, "auth_b", null, null);
    expect(first.created).toBe(true);
    expect(second.created).toBe(false);
    expect(second.order.id).toBe(first.order.id);
  });
});
