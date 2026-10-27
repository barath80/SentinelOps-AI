import type { NextConfig } from "next";

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
};

export default nextConfig;
