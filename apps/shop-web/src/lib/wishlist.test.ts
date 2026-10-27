import { describe, expect, it } from "vitest";
import { addToWishlist, isInWishlist, listWishlistProductIds, removeFromWishlist } from "./wishlist";

describe("wishlist", () => {
  it("adds, lists, and checks membership", async () => {
    expect(await isInWishlist("u1", "p1")).toBe(false);
    await addToWishlist("u1", "p1");
    expect(await isInWishlist("u1", "p1")).toBe(true);
    expect(await listWishlistProductIds("u1")).toEqual(["p1"]);
  });

  it("is idempotent when adding the same product twice", async () => {
    await addToWishlist("u1", "p1");
    await addToWishlist("u1", "p1");
    expect(await listWishlistProductIds("u1")).toEqual(["p1"]);
  });

  it("removes a product from the wishlist", async () => {
    await addToWishlist("u1", "p1");
    await removeFromWishlist("u1", "p1");
    expect(await listWishlistProductIds("u1")).toEqual([]);
  });

  it("keeps wishlists separate per user", async () => {
    await addToWishlist("u1", "p1");
    await addToWishlist("u2", "p2");
    expect(await listWishlistProductIds("u1")).toEqual(["p1"]);
    expect(await listWishlistProductIds("u2")).toEqual(["p2"]);
  });
});
