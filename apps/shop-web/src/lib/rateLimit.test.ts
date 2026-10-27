import { afterEach, describe, expect, it, vi } from "vitest";
import { checkRateLimit, clientIp } from "./rateLimit";

afterEach(() => {
  vi.useRealTimers();
});

describe("checkRateLimit", () => {
  it("allows requests up to the limit", async () => {
    for (let i = 0; i < 3; i++) {
      expect((await checkRateLimit("k1", 3, 60)).allowed).toBe(true);
    }
  });

  it("denies requests once the limit is exceeded", async () => {
    for (let i = 0; i < 3; i++) await checkRateLimit("k2", 3, 60);
    const result = await checkRateLimit("k2", 3, 60);
    expect(result.allowed).toBe(false);
    expect(result.retryAfterSeconds).toBeGreaterThan(0);
  });

  it("resets the count once the window has elapsed", async () => {
    vi.useFakeTimers();
    await checkRateLimit("k3", 1, 1);
    expect((await checkRateLimit("k3", 1, 1)).allowed).toBe(false);
    vi.advanceTimersByTime(1100);
    expect((await checkRateLimit("k3", 1, 1)).allowed).toBe(true);
  });

  it("tracks separate keys independently", async () => {
    await checkRateLimit("a", 1, 60);
    expect((await checkRateLimit("a", 1, 60)).allowed).toBe(false);
    expect((await checkRateLimit("b", 1, 60)).allowed).toBe(true);
  });
});

describe("clientIp", () => {
  it("reads the first address from x-forwarded-for", () => {
    const req = new Request("http://localhost", { headers: { "x-forwarded-for": "1.2.3.4, 5.6.7.8" } });
    expect(clientIp(req)).toBe("1.2.3.4");
  });

  it("falls back to 'unknown' when absent", () => {
    expect(clientIp(new Request("http://localhost"))).toBe("unknown");
  });
});
