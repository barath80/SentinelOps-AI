import type { MetadataRoute } from "next";
import { PRODUCTS } from "@/lib/products";
import { siteUrl } from "@/lib/seo";

export default function sitemap(): MetadataRoute.Sitemap {
  const base = siteUrl();
  const staticRoutes: MetadataRoute.Sitemap = [
    { url: base, changeFrequency: "daily", priority: 1 },
    { url: `${base}/search`, changeFrequency: "daily", priority: 0.8 },
    { url: `${base}/deals`, changeFrequency: "daily", priority: 0.8 },
  ];
  const productRoutes: MetadataRoute.Sitemap = PRODUCTS.map((p) => ({
    url: `${base}/products/${p.id}`,
    changeFrequency: "weekly",
    priority: 0.6,
  }));
  return [...staticRoutes, ...productRoutes];
}
