import { afterEach, describe, expect, it, vi } from "vitest";
import { cached, CACHE_TIMEOUT_MS, clearCache } from "./cache";
import { burnCpu, clockOffsetMs, CLOCK_AHEAD_MS, setOverride } from "./faults";
import { ACQUIRE_TIMEOUT_MS, poolStats, POOL_SIZE, withConnection } from "./pool";
import { authorizeWithRetry, MAX_ATTEMPTS, PaymentTimeout, ProviderUnavailable } from "./payment";
import { runTrace, setSpanSink, type SpanRecord } from "./trace";

afterEach(() => {
  setOverride(undefined);
  clearCache();
  vi.useRealTimers();
});

// Collects the spans one traced call produces (the sink normally feeds the telemetry pusher).
async function spansOf<T>(fn: () => Promise<T>): Promise<{ result?: T; error?: unknown; spans: SpanRecord[] }> {
  const spans: SpanRecord[] = [];
  setSpanSink((s) => spans.push(s));
  try {
    const result = await runTrace("test", {}, fn);
    return { result, spans };
  } catch (error) {
    return { error, spans };
  } finally {
    setSpanSink(() => {});
  }
}

const ms = (s: SpanRecord) => Number(BigInt(s.endTimeUnixNano) - BigInt(s.startTimeUnixNano)) / 1e6;

describe("S02 connection pool", () => {
  it("records a fast acquire span and returns the permit when healthy", async () => {
    const { result, spans } = await spansOf(() => withConnection(async () => "row"));
    expect(result).toBe("row");
    expect(spans.find((s) => s.name === "db.pool.acquire")).toBeDefined();
    expect(poolStats()).toEqual({ free: POOL_SIZE, waiting: 0 });
  });

  it("returns the permit even when the query throws", async () => {
    await spansOf(() => withConnection(async () => { throw new Error("query failed"); }));
    expect(poolStats().free).toBe(POOL_SIZE);
  });

  it("waits out the acquire timeout when the pool is exhausted, while the query stays fast", async () => {
    vi.useFakeTimers();
    setOverride("S02_db_pool_exhaustion");
    const pending = spansOf(() => withConnection(async () => "row"));
    await vi.advanceTimersByTimeAsync(ACQUIRE_TIMEOUT_MS);
    const { result, spans } = await pending;
    expect(result).toBe("row");
    expect(ms(spans.find((s) => s.name === "db.pool.acquire")!)).toBeGreaterThanOrEqual(ACQUIRE_TIMEOUT_MS - 1);
  });
});

describe("S04 cache", () => {
  it("serves the second lookup from the cache", async () => {
    const load = vi.fn(() => ["p1"]);
    await cached("k", load);
    expect(await cached("k", load)).toEqual(["p1"]);
    expect(load).toHaveBeenCalledTimes(1);
  });

  it("falls back to the origin when the cache is down, with failed cache spans", async () => {
    vi.useFakeTimers();
    setOverride("S04_cache_unavailable");
    const pending = spansOf(() => cached("k", () => ["p1"]));
    await vi.advanceTimersByTimeAsync(CACHE_TIMEOUT_MS * 2);
    const { result, spans } = await pending;
    expect(result).toEqual(["p1"]);
    const cacheSpans = spans.filter((s) => s.name.startsWith("cache."));
    expect(cacheSpans.map((s) => s.name)).toEqual(["cache.get catalogue", "cache.set catalogue"]);
    expect(cacheSpans.every((s) => s.status.code === 2)).toBe(true);
  });
});

describe("S07 retry policy", () => {
  it("makes one provider call when the provider is healthy", async () => {
    const onRetry = vi.fn();
    const { result, spans } = await spansOf(() => authorizeWithRetry(1000, onRetry));
    expect(result).toMatchObject({ approved: true });
    expect(spans.filter((s) => s.name === "payment.authorize")).toHaveLength(1);
    expect(onRetry).not.toHaveBeenCalled();
  });

  it("retries a flaky provider immediately and records one span per attempt", async () => {
    vi.useFakeTimers();
    setOverride("S07_retry_storm");
    const rolls = [0.1, 0.1, 0.1, 0.9]; // three transient failures, then success
    const onRetry = vi.fn();
    const pending = spansOf(() => authorizeWithRetry(1000, onRetry, () => rolls.shift()!));
    await vi.advanceTimersByTimeAsync(2000);
    const { result, spans } = await pending;
    expect(result).toMatchObject({ approved: true });
    expect(spans.filter((s) => s.name === "payment.authorize")).toHaveLength(4);
    expect(onRetry.mock.calls.map((c) => c[0])).toEqual([1, 2, 3]);
  });

  it("gives up after the last attempt", async () => {
    vi.useFakeTimers();
    setOverride("S07_retry_storm");
    const pending = spansOf(() => authorizeWithRetry(1000, () => {}, () => 0));
    await vi.advanceTimersByTimeAsync(5000);
    const { error, spans } = await pending;
    expect(error).toBeInstanceOf(ProviderUnavailable);
    expect(spans.filter((s) => s.name === "payment.authorize")).toHaveLength(MAX_ATTEMPTS);
  });

  it("never retries a timeout", async () => {
    vi.useFakeTimers();
    setOverride("S05_payment_timeout");
    const onRetry = vi.fn();
    const pending = spansOf(() => authorizeWithRetry(1000, onRetry));
    await vi.advanceTimersByTimeAsync(3000);
    expect((await pending).error).toBeInstanceOf(PaymentTimeout);
    expect(onRetry).not.toHaveBeenCalled();
  });
});

describe("S06 and S11", () => {
  it("burns CPU for the requested time", () => {
    const start = performance.now();
    burnCpu(30);
    expect(performance.now() - start).toBeGreaterThanOrEqual(30);
  });

  it("runs the telemetry clock ahead only under S11", () => {
    expect(clockOffsetMs()).toBe(0);
    setOverride("S11_clock_skew");
    expect(clockOffsetMs()).toBe(CLOCK_AHEAD_MS);
  });
});
