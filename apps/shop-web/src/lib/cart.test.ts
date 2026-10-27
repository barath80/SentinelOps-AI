import { describe, expect, it } from "vitest";
import { cookieStore } from "../test/setup";
import { detail, MAX_QTY, readCart, sameLine, writeCart } from "./cart";
import { getProduct } from "./products";

describe("readCart", () => {
  it("returns an empty cart when no cookie is set", async () => {
    expect(await readCart()).toEqual([]);
  });

  it("drops malformed cookie JSON", async () => {
    cookieStore.set("cart", { value: "not json" });
    expect(await readCart()).toEqual([]);
  });

  it("drops lines for unknown product ids", async () => {
    cookieStore.set("cart", { value: JSON.stringify([{ id: "does-not-exist", qty: 1 }]) });
    expect(await readCart()).toEqual([]);
  });

  it("caps quantity at MAX_QTY", async () => {
    cookieStore.set("cart", { value: JSON.stringify([{ id: "p1", qty: 999 }]) });
    const cart = await readCart();
    expect(cart[0].qty).toBe(MAX_QTY);
  });

  it("caps the number of lines at 20", async () => {
    const lines = Array.from({ length: 30 }, (_, i) => ({ id: `p${i + 1}`, qty: 1 }));
    cookieStore.set("cart", { value: JSON.stringify(lines) });
    expect((await readCart()).length).toBe(20);
  });

  it("round-trips through writeCart", async () => {
    await writeCart([{ id: "p1", qty: 2, color: getProduct("p1")!.colors[0].name }]);
    const cart = await readCart();
    expect(cart).toHaveLength(1);
    expect(cart[0]).toMatchObject({ id: "p1", qty: 2 });
  });
});

describe("sameLine", () => {
  it("matches on id and color", () => {
    expect(sameLine({ id: "p1", qty: 1, color: "Black" }, "p1", "Black")).toBe(true);
    expect(sameLine({ id: "p1", qty: 1, color: "Black" }, "p1", "White")).toBe(false);
  });
});

describe("detail", () => {
  it("computes totals and counts across lines", () => {
    const p1 = getProduct("p1")!;
    const p2 = getProduct("p13")!;
    const { lines, totalCents, count } = detail([
      { id: p1.id, qty: 2, color: p1.colors[0].name },
      { id: p2.id, qty: 1, color: p2.colors[0].name },
    ]);
    expect(lines).toHaveLength(2);
    expect(totalCents).toBe(p1.priceCents * 2 + p2.priceCents);
    expect(count).toBe(3);
  });

  it("silently skips lines for products that no longer exist", () => {
    const { lines, totalCents, count } = detail([{ id: "does-not-exist", qty: 1, color: "Black" }]);
    expect(lines).toEqual([]);
    expect(totalCents).toBe(0);
    expect(count).toBe(0);
  });
});
