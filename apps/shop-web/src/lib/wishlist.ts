import { db } from "./db";

export async function isInWishlist(userId: string, productId: string): Promise<boolean> {
  const rows = (await db()`
    SELECT 1 FROM wishlist_items WHERE user_id = ${userId} AND product_id = ${productId}`) as unknown[];
  return rows.length > 0;
}

export async function listWishlistProductIds(userId: string): Promise<string[]> {
  const rows = (await db()`
    SELECT product_id FROM wishlist_items WHERE user_id = ${userId} ORDER BY created_at DESC`) as { product_id: string }[];
  return rows.map((r) => r.product_id);
}

export async function addToWishlist(userId: string, productId: string): Promise<void> {
  await db()`
    INSERT INTO wishlist_items (user_id, product_id) VALUES (${userId}, ${productId})
    ON CONFLICT (user_id, product_id) DO NOTHING`;
}

export async function removeFromWishlist(userId: string, productId: string): Promise<void> {
  await db()`DELETE FROM wishlist_items WHERE user_id = ${userId} AND product_id = ${productId}`;
}
