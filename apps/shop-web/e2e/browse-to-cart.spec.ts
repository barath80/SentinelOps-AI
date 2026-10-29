import { expect, test } from "@playwright/test";

// These specs cover flows that don't touch Postgres (catalogue is in-memory, cart is a cookie).
// Checkout runs against the in-memory store: see checkout.spec.ts.

test("home page loads and links to a product", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("link", { name: /ShopSphere/i })).toBeVisible();
  const firstProductLink = page.locator('a[href^="/products/"]').first();
  await firstProductLink.click();
  await expect(page).toHaveURL(/\/products\/p\d+/);
});

test("search finds products and the result links to a product page", async ({ page }) => {
  await page.goto("/search?q=headphones");
  await expect(page.locator('a[href^="/products/"]').first()).toBeVisible();
});

test("an unknown product id shows a not-found response", async ({ page }) => {
  const res = await page.goto("/products/does-not-exist");
  expect(res?.status()).toBe(404);
});

test("add to cart updates the cart badge and the cart page", async ({ page }) => {
  await page.goto("/products/p1");
  // BuyBox renders both the main add-to-cart button and a mobile sticky-bar duplicate.
  await page.getByRole("button", { name: "Add to cart", exact: true }).first().click();
  await expect(page.getByRole("button", { name: /Added to cart/i }).first()).toBeVisible();

  await page.goto("/cart");
  await expect(page.getByRole("heading", { name: "Shopping cart" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Delete" })).toBeVisible();
});

test("an empty cart shows the empty state", async ({ page, context }) => {
  await context.clearCookies();
  await page.goto("/cart");
  await expect(page.getByRole("heading", { name: "Your cart is empty" })).toBeVisible();
});

test("the mobile nav drawer opens and links to a category", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByRole("button", { name: "Open menu" }).click();
  await expect(page.getByRole("heading", { name: "Shop by department" })).toBeVisible();
  await page.getByRole("link", { name: "Electronics" }).click();
  await expect(page).toHaveURL(/category=electronics/);
});

test("the cart drawer opens from the header and shows an added item", async ({ page }) => {
  await page.goto("/products/p1");
  await page.getByRole("button", { name: "Add to cart", exact: true }).first().click();
  await expect(page.getByRole("button", { name: /Added to cart/i }).first()).toBeVisible();

  await page.getByRole("button", { name: /^Cart, \d+ items?$/ }).click();
  await expect(page.getByRole("heading", { name: "Your cart" })).toBeVisible();
  await expect(page.getByText("Subtotal:")).toBeVisible();
});
