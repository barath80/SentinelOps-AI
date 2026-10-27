import { describe, expect, it } from "vitest";
import { GET } from "./route";

const ctx = (id: string) => ({ params: Promise.resolve({ id }) });

describe("GET /api/products/[id]", () => {
  it("returns the product for a known id", async () => {
    const res = await GET(new Request("http://localhost/api/products/p1"), ctx("p1"));
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.product.id).toBe("p1");
  });

  // Regression test: the page previously streamed a 200 shell before `notFound()` resolved.
  // The API route itself has always been correct, but this pins the contract the UI fix (Phase 1)
  // must match.
  it("returns 404 for an unknown id", async () => {
    const res = await GET(new Request("http://localhost/api/products/does-not-exist"), ctx("does-not-exist"));
    expect(res.status).toBe(404);
  });
});
