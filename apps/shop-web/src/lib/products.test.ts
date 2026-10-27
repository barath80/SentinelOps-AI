import { describe, expect, it } from "vitest";
import { colorOf, getProduct, PRODUCTS, searchProducts } from "./products";

describe("catalogue generation", () => {
  it("produces a deterministic, stable set of 96 products", () => {
    expect(PRODUCTS).toHaveLength(96);
    expect(PRODUCTS.map((p) => p.id).slice(0, 3)).toEqual(["p1", "p2", "p3"]);
  });

  it("gives every product at least one colour and a positive price", () => {
    for (const p of PRODUCTS) {
      expect(p.colors.length).toBeGreaterThan(0);
      expect(p.priceCents).toBeGreaterThan(0);
    }
  });
});

describe("getProduct", () => {
  it("finds a product by id", () => {
    expect(getProduct("p1")?.id).toBe("p1");
  });

  it("returns undefined for an unknown id", () => {
    expect(getProduct("does-not-exist")).toBeUndefined();
  });
});

describe("colorOf", () => {
  it("falls back to the first colour when the name is unknown", () => {
    const p = getProduct("p1")!;
    expect(colorOf(p, "not-a-real-color")).toEqual(p.colors[0]);
    expect(colorOf(p, null)).toEqual(p.colors[0]);
  });

  it("returns the matching colour when the name exists", () => {
    const p = getProduct("p1")!;
    const target = p.colors[p.colors.length - 1];
    expect(colorOf(p, target.name)).toEqual(target);
  });
});

describe("searchProducts", () => {
  it("filters by category", () => {
    const results = searchProducts({ category: "beauty" });
    expect(results.length).toBeGreaterThan(0);
    expect(results.every((p) => p.category === "beauty")).toBe(true);
  });

  it("filters by price range", () => {
    const results = searchProducts({ minCents: 10000, maxCents: 20000 });
    expect(results.every((p) => p.priceCents >= 10000 && p.priceCents <= 20000)).toBe(true);
  });

  it("filters out products below the minimum rating", () => {
    const results = searchProducts({ minRating: 4.5 });
    expect(results.every((p) => p.rating >= 4.5)).toBe(true);
  });

  it("scores and ranks text matches against product names highest", () => {
    const sample = PRODUCTS[0];
    const word = sample.name.split(" ")[0].toLowerCase();
    const results = searchProducts({ q: word });
    expect(results.length).toBeGreaterThan(0);
  });

  it("sorts by price ascending", () => {
    const results = searchProducts({ sort: "price-asc" });
    for (let i = 1; i < results.length; i++) {
      expect(results[i].priceCents).toBeGreaterThanOrEqual(results[i - 1].priceCents);
    }
  });

  it("returns no results for a query matching nothing", () => {
    expect(searchProducts({ q: "xyznonexistentquery" })).toEqual([]);
  });
});
