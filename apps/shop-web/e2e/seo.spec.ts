import { expect, test } from "@playwright/test";

test("robots.txt disallows account/transactional routes and points at the sitemap", async ({ request }) => {
  const res = await request.get("/robots.txt");
  expect(res.status()).toBe(200);
  const body = await res.text();
  expect(body).toContain("Disallow: /cart");
  expect(body).toContain("Disallow: /checkout");
  expect(body).toContain("Sitemap:");
});

test("sitemap.xml lists the full product catalogue", async ({ request }) => {
  const res = await request.get("/sitemap.xml");
  expect(res.status()).toBe(200);
  const body = await res.text();
  expect(body).toContain("<urlset");
  // 96 products + 3 static routes (home, search, deals).
  expect(body.match(/<url>/g)?.length).toBe(99);
});

test("a product page has a canonical link and Product/BreadcrumbList JSON-LD", async ({ page }) => {
  await page.goto("/products/p1");
  await expect(page.locator('link[rel="canonical"]')).toHaveAttribute("href", /\/products\/p1$/);

  const jsonLd = await page.locator('script[type="application/ld+json"]').allTextContents();
  const parsed = jsonLd.map((t) => JSON.parse(t));
  expect(parsed.some((d) => d["@type"] === "Product" && d.sku === "p1")).toBe(true);
  expect(parsed.some((d) => d["@type"] === "BreadcrumbList")).toBe(true);
});

test("account/transactional pages are marked noindex", async ({ page }) => {
  await page.goto("/cart");
  await expect(page.locator('meta[name="robots"]')).toHaveAttribute("content", /noindex/);
});
