import type { NextConfig } from "next";

// No nonce-based CSP infrastructure (would need middleware threading a per-request nonce into
// every inline script), so script-src keeps 'unsafe-inline' for Next's own hydration bootstrap
// scripts. Everything else is locked to same-origin; there are no third-party image/font/script
// CDNs (fonts are self-hosted via next/font, product art is inline SVG, OG images are same-origin).
// 'unsafe-eval' is added only outside production: React dev mode uses eval() for debugging
// (reconstructing stack traces across environments) and never does in a production build.
const CSP = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${process.env.NODE_ENV === "production" ? "" : " 'unsafe-eval'"}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  "font-src 'self' data:",
  "connect-src 'self'",
  "frame-ancestors 'none'",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
].join("; ");

const SECURITY_HEADERS = [
  { key: "Content-Security-Policy", value: CSP },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
  ...(process.env.NODE_ENV === "production"
    ? [{ key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains; preload" }]
    : []),
];

const nextConfig: NextConfig = {
  // Cache Components (PPR) is off: it makes every dynamic page serve a static, id-independent
  // shell with status 200 up front and resolve the real content afterward, which means
  // notFound()/redirect() can never actually change the response status for routes like
  // /products/[id] and /order/[id]. Correct HTTP status codes matter more here than the
  // (experimental, early-stage) streaming shell optimization.
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async headers() {
    return [{ source: "/:path*", headers: SECURITY_HEADERS }];
  },
};

export default nextConfig;
