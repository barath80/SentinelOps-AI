import { instrument } from "@/lib/handler";
import { searchProducts, type SortKey } from "@/lib/products";

const SORTS: SortKey[] = ["relevance", "price-asc", "price-desc", "rating", "reviews", "bestsellers"];
const PAGE_SIZE = 24;

// GET /api/products?q=&category=&brand=&min=&max=&rating=&sort=&page=  (min/max in dollars)
export const GET = instrument("/api/products", async (req) => {
  const sp = new URL(req.url).searchParams;
  const num = (k: string) => (sp.get(k) && Number.isFinite(Number(sp.get(k))) ? Number(sp.get(k)) : undefined);
  const sort = sp.get("sort") as SortKey | null;
  const results = searchProducts({
    q: sp.get("q") ?? undefined,
    category: sp.get("category") ?? undefined,
    brand: sp.get("brand") ?? undefined,
    minCents: num("min") !== undefined ? Math.round(num("min")! * 100) : undefined,
    maxCents: num("max") !== undefined ? Math.round(num("max")! * 100) : undefined,
    minRating: num("rating"),
    sort: sort && SORTS.includes(sort) ? sort : "relevance",
  });
  const page = Math.max(1, Math.floor(num("page") ?? 1));
  return Response.json({
    total: results.length,
    page,
    pageSize: PAGE_SIZE,
    products: results.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE),
  });
});
