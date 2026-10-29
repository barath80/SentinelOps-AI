import { expect, test } from "@playwright/test";

// The full purchase journey in a real browser. The dev server runs with SHOP_DB=memory (see
// playwright.config.ts), so orders go to the in-memory store and no real database is touched.

test("a guest can buy a product and see the order confirmation", async ({ page }) => {
  await page.goto("/products/p1");
  await page.getByRole("button", { name: "Add to cart", exact: true }).first().click();
  await expect(page.getByRole("button", { name: /Added to cart/i }).first()).toBeVisible();

  await page.goto("/checkout");
  await expect(page.getByRole("heading", { name: "Checkout" })).toBeVisible();
  await page.getByLabel("Email (for your order confirmation)").fill("guest@example.com");
  await page.getByLabel("Full name").fill("Ada Lovelace");
  await page.getByLabel("Address").fill("1 Analytical Engine Way");
  await page.getByLabel("City").fill("London");
  await page.getByLabel("Postal code").fill("AB1 2CD");
  await page.getByLabel("Country").fill("UK");
  await page.getByRole("button", { name: "Place your order" }).click();

  await expect(page).toHaveURL(/\/order\/ord_[0-9a-f]{16}$/);
  await expect(page.getByText("Order placed, thank you!")).toBeVisible();
});

test("checkout API is idempotent and an unknown order is a 404", async ({ request }) => {
  await request.post("/api/cart", { data: { id: "p2", qty: 1 } });
  const key = `e2e-${Date.now()}`;
  const first = await request.post("/api/checkout", { headers: { "idempotency-key": key } });
  expect(first.status()).toBe(201);
  const order = (await first.json()).order;
  await request.post("/api/cart", { data: { id: "p2", qty: 1 } });
  const again = await request.post("/api/checkout", { headers: { "idempotency-key": key } });
  expect((await again.json()).order.id).toBe(order.id); // a retried checkout never creates a second order
  expect((await request.get("/api/orders/ord_0000000000000000")).status()).toBe(404);
});
