import type { Metadata } from "next";
import { formatPrice, type Product } from "./products";

export const SITE_NAME = "ShopSphere";
export const SITE_DESCRIPTION =
  "Demo online store used as a workload for SentinelOps AI. Fictional brands; no real payments.";

// Same fallback pattern as src/lib/google.ts: APP_URL in production/preview, localhost in dev.
export function siteUrl(): string {
  return (process.env.APP_URL ?? "http://localhost:3000").replace(/\/$/, "");
}

// Applied to transactional/account pages: no SEO value, and some expose user-specific state.
export const NOINDEX: Metadata = {
  robots: { index: false, follow: false },
};

export function buildProductJsonLd(p: Product, url: string) {
  return {
    "@context": "https://schema.org",
    "@type": "Product",
    name: p.name,
    brand: { "@type": "Brand", name: p.brand },
    sku: p.id,
    description: p.description,
    image: `${siteUrl()}/products/${p.id}/opengraph-image`,
    offers: {
      "@type": "Offer",
      url,
      priceCurrency: "USD",
      price: (p.priceCents / 100).toFixed(2),
      availability: p.stock > 0 ? "https://schema.org/InStock" : "https://schema.org/OutOfStock",
    },
    ...(p.reviewCount > 0 && {
      aggregateRating: {
        "@type": "AggregateRating",
        ratingValue: p.rating,
        reviewCount: p.reviewCount,
      },
    }),
  };
}

export function buildBreadcrumbJsonLd(items: { name: string; url: string }[]) {
  return {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: items.map((item, i) => ({
      "@type": "ListItem",
      position: i + 1,
      name: item.name,
      item: item.url,
    })),
  };
}

export function buildWebsiteJsonLd() {
  const base = siteUrl();
  return {
    "@context": "https://schema.org",
    "@type": "WebSite",
    name: SITE_NAME,
    url: base,
    potentialAction: {
      "@type": "SearchAction",
      target: `${base}/search?q={search_term_string}`,
      "query-input": "required name=search_term_string",
    },
  };
}

// Product prices change per build (synthetic/seeded), so the description includes the price at
// render time rather than baking it into static copy.
export function productMetaDescription(p: Product): string {
  return `${p.name} by ${p.brand} — ${formatPrice(p.priceCents)}. ${p.bullets[0]}.`;
}
